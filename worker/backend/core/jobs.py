"""Gestor de trabajos: cola secuencial (una GPU), eventos SSE, cancelación."""
from __future__ import annotations

import asyncio
import json
import queue as _queue
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from backend import config
from backend.pipeline.runner import RunnerContext, Progress, CancelledError


@dataclass
class Job:
    id: str
    kind: str                  # 'demo' | 'full'
    source: str
    filename: str
    cfg: dict
    probe: dict
    segment_start: float
    segment_duration: float
    state: str = "queued"      # queued|running|done|error|cancelled
    created_at: float = field(default_factory=time.time)
    progress: dict = field(default_factory=dict)
    output: str | None = None
    error: str | None = None
    simulate: bool = False

    def public(self) -> dict:
        d = asdict(self)
        d.pop("probe", None)
        return d


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._queue: _queue.Queue[str] = _queue.Queue()
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_id = 0
        self._worker = threading.Thread(target=self._work_loop, daemon=True,
                                        name="job-worker")
        self._worker.start()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── API pública ─────────────────────────────────────────────────────────
    def submit(self, kind: str, source: str, cfg: dict, probe: dict,
               segment_start: float, segment_duration: float,
               simulate: bool) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, source=source,
                  filename=Path(source).name, cfg=cfg, probe=probe,
                  segment_start=segment_start,
                  segment_duration=segment_duration, simulate=simulate)
        self.jobs[job.id] = job
        self._cancel_events[job.id] = threading.Event()
        self._queue.put(job.id)
        self._emit(job)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
        if job.state == "queued":
            job.state = "cancelled"
            self._emit(job)
        return True

    def workdir(self, job: Job) -> Path:
        """Directorio determinista por (fichero, config, segmento) — NO por id:
        así relanzar el mismo trabajo tras reiniciar la app reutiliza los
        chunks ya completados (reanudación real)."""
        import hashlib
        import json as _json
        key = _json.dumps([job.source, job.cfg, job.kind, job.segment_start,
                           job.segment_duration], sort_keys=True)
        digest = hashlib.sha1(key.encode()).hexdigest()[:16]
        d = config.JOBS_DIR / digest
        d.mkdir(parents=True, exist_ok=True)
        return d

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ── interno ──────────────────────────────────────────────────────────────
    def _emit(self, job: Job) -> None:
        if self._loop is None:
            return
        self._event_id += 1
        payload = json.dumps({"id": self._event_id, "job": job.public()},
                             ensure_ascii=False)
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, payload)
            except RuntimeError:
                pass

    def _work_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.state == "cancelled":
                continue
            cancel = self._cancel_events[job_id]
            job.state = "running"
            self._emit(job)

            last_emit = 0.0

            def on_progress(p: Progress, _job=job):
                nonlocal last_emit
                _job.progress = {k: v for k, v in asdict(p).items() if v is not None}
                now = time.monotonic()
                # limitar a ~4 eventos/s salvo cambios de etapa
                if now - last_emit > 0.25 or p.stage in ("completado",):
                    last_emit = now
                    self._emit(_job)

            try:
                ctx = RunnerContext(
                    job_id=job.id, source=job.source, probe=job.probe,
                    cfg=job.cfg, segment_start=job.segment_start,
                    segment_duration=job.segment_duration,
                    is_demo=(job.kind == "demo"), workdir=self.workdir(job),
                    on_progress=on_progress, cancel=cancel,
                    simulate=job.simulate)
                out = ctx.run()
                job.output = str(out)
                job.state = "done"
            except CancelledError:
                job.state = "cancelled"
            except Exception as e:  # noqa: BLE001 — el error viaja a la UI
                job.state = "error"
                job.error = f"{type(e).__name__}: {e}"
            self._emit(job)


manager = JobManager()
