"""Orquestador de una conversión (demo o película completa).

Por chunk de escena: decode (pipe) → profundidad (VDA) → estéreo (rápido/HQ)
→ SBS → encode a chunk_NNNN.mkv. Al final: concat sin recodificar + remux con
audio/subs/capítulos del original. Manifest JSON por job → reanudable.

En RAM solo viven sub-lotes de _batch_frames() frames (adaptativo a la RAM).
La normalización de profundidad usa EMA entre lotes para evitar parpadeo
(idea de iw3 --ema-normalize).
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import numpy as np

from backend import config
from backend.core import estimator
from backend.pipeline import decode, encode, mux, scenes
from backend.pipeline.sbs import compose_sbs

EMA_DECAY = 0.9


def _batch_frames(proc_res: str, ram_gb: float) -> int:
    """Frames por lote según RAM: con el solape profundidad/warp hay hasta DOS
    lotes vivos a la vez (más depth + ojos izq/dcho), así que en equipos de
    16 GB compartidos los lotes grandes provocan MemoryError."""
    if proc_res == "4k":
        return 12 if ram_gb >= 24 else 8
    if ram_gb >= 24:
        return 48
    return 24 if ram_gb >= 12 else 12


@dataclass
class Progress:
    stage: str = "preparando"
    frames_done: int = 0
    frames_total: int = 0
    fps: float = 0.0
    chunk: int = 0
    chunks_total: int = 0
    eta_s: float | None = None
    thumbnail: str | None = None  # jpeg base64 del depth map (feedback visual)
    message: str | None = None


class CancelledError(Exception):
    pass


@dataclass
class RunnerContext:
    job_id: str
    source: str
    probe: dict
    cfg: dict                      # proc_res, depth_model, mode, inpaint_steps,
                                   # output, divergence, convergence, tonemap
    segment_start: float
    segment_duration: float
    is_demo: bool
    workdir: Path
    on_progress: callable
    cancel: Event
    simulate: bool = False
    _ema_min: float | None = field(default=None, init=False)
    _ema_max: float | None = field(default=None, init=False)

    # ── utilidades ──────────────────────────────────────────────────────────
    def _check_cancel(self):
        if self.cancel.is_set():
            raise CancelledError()

    def _manifest_path(self) -> Path:
        return self.workdir / "manifest.json"

    def _load_manifest(self) -> dict:
        p = self._manifest_path()
        if p.exists():
            try:
                m = json.loads(p.read_text("utf-8"))
                if m.get("cfg") == self.cfg:   # solo reanudar si config idéntica
                    return m
            except (json.JSONDecodeError, OSError):
                pass
        return {"cfg": self.cfg, "chunks_done": []}

    def _save_manifest(self, m: dict) -> None:
        self._manifest_path().write_text(json.dumps(m, indent=2), "utf-8")

    def _normalize_depth_ema(self, d: np.ndarray) -> np.ndarray:
        """Alinea la escala de profundidad entre lotes (anti-parpadeo)."""
        lo, hi = float(np.percentile(d, 1)), float(np.percentile(d, 99))
        if self._ema_min is None:
            self._ema_min, self._ema_max = lo, hi
        else:
            self._ema_min = EMA_DECAY * self._ema_min + (1 - EMA_DECAY) * lo
            self._ema_max = EMA_DECAY * self._ema_max + (1 - EMA_DECAY) * hi
        rng = max(self._ema_max - self._ema_min, 1e-6)
        return np.clip((d - self._ema_min) / rng, 0.0, 1.0)

    def _depth_thumbnail(self, d: np.ndarray) -> str | None:
        try:
            import cv2
            small = cv2.resize((d * 255).astype(np.uint8), (256, 144))
            ok, jpg = cv2.imencode(".jpg", cv2.applyColorMap(small, cv2.COLORMAP_INFERNO))
            return base64.b64encode(jpg.tobytes()).decode() if ok else None
        except ImportError:
            return None

    # ── ejecución ───────────────────────────────────────────────────────────
    def run(self) -> Path:
        if self.simulate:
            return self._run_simulated()
        return self._run_real()

    def _run_real(self) -> Path:
        from backend.pipeline.depth import create_depth_estimator

        cfg = self.cfg
        fps = self.probe["video"]["fps"] or 24.0
        frames_total = int(self.segment_duration * fps)
        prog = Progress(frames_total=frames_total, stage="detectando escenas")
        self.on_progress(prog)

        chunks = scenes.detect_chunks(self.source, self.segment_start,
                                      self.segment_duration)
        prog.chunks_total = len(chunks)
        manifest = self._load_manifest()

        prog.stage = "cargando modelos"
        self.on_progress(prog)
        window = 32 if cfg.get("vram_ok", True) else 16
        depth_est = create_depth_estimator(cfg["depth_model"], window=window)
        if cfg["mode"] == "hq":
            from backend.pipeline.stereo_hq import HQStereo
            stereo = HQStereo(cfg["divergence"], cfg["convergence"],
                              steps=cfg.get("inpaint_steps", 8),
                              inpaint_downscale=cfg.get("inpaint_downscale", True))
        else:
            from backend.pipeline.stereo_fast import FastStereo
            stereo = FastStereo(cfg["divergence"], cfg["convergence"])

        tonemap = bool(self.probe["video"].get("hdr")) and cfg.get("tonemap", True)
        stage_times: dict[str, list[float]] = {"depth": [], "stereo": []}
        t_start = time.monotonic()
        from backend.core.compute import detect_compute
        batch_size = _batch_frames(cfg["proc_res"], detect_compute().ram_gb or 16.0)

        try:
            for chunk in chunks:
                self._check_cancel()
                seg_path = self.workdir / f"chunk_{chunk.index:05d}.mkv"
                if chunk.index in manifest["chunks_done"] and seg_path.exists():
                    prog.frames_done += int(chunk.duration_s * fps)
                    continue
                enc = encode.SegmentEncoder(seg_path, cfg["output"], fps)
                try:
                    self._run_chunk_overlapped(chunk, fps, batch_size, tonemap,
                                               depth_est, stereo, enc, prog,
                                               stage_times, t_start)
                finally:
                    enc.close()
                manifest["chunks_done"].append(chunk.index)
                self._save_manifest(manifest)
                prog.chunk = chunk.index + 1
                self.on_progress(prog)
        finally:
            depth_est.close()
            if hasattr(stereo, "close"):
                stereo.close()
            self._save_calibration(stage_times, cfg)

        # concat + remux + preview
        prog.stage = "uniendo y remuxando"
        self.on_progress(prog)
        joined = self.workdir / "video3d.mkv"
        seg_files = [self.workdir / f"chunk_{c.index:05d}.mkv" for c in chunks]
        encode.concat_segments(seg_files, joined)
        out_path = self._output_path()
        mux.mux_final(joined, self.source, out_path, cfg["output"],
                      is_demo=self.is_demo,
                      demo_start_s=self.segment_start if self.is_demo else None,
                      demo_duration_s=self.segment_duration if self.is_demo else None)
        if self.is_demo:
            prog.stage = "generando preview"
            self.on_progress(prog)
            try:
                encode.make_preview(joined, self.workdir / "preview.mp4", h264=False)
            except encode.EncodeError:
                pass
            encode.make_preview(joined, self.workdir / "preview_h264.mp4", h264=True)
        prog.stage = "completado"
        prog.message = str(out_path)
        self.on_progress(prog)
        return out_path

    def _run_chunk_overlapped(self, chunk, fps, batch_size, tonemap,
                              depth_est, stereo, enc, prog, stage_times,
                              t_start):
        """Solapa etapas: profundidad (iGPU/DML) en este hilo, warp+encode
        (CPU) en un hilo consumidor. ORT y torch sueltan el GIL durante el
        cómputo, así que el solape es real. Cola de tamaño 1: como mucho dos
        lotes vivos en RAM."""
        import queue as _queue
        import threading

        work_q: _queue.Queue = _queue.Queue(maxsize=1)
        consumer_error: list[BaseException] = []

        def consumer():
            while True:
                item = work_q.get()
                if item is None:
                    return
                frames, depths = item
                try:
                    t1 = time.monotonic()
                    left, right = stereo.process(frames, depths)
                    for l, r in zip(left, right):
                        enc.write(compose_sbs(l, r, self.cfg["output"]))
                    n = len(frames)
                    stage_times["stereo"].append(
                        n / max(time.monotonic() - t1, 1e-3))
                    prog.frames_done += n
                    elapsed = time.monotonic() - t_start
                    prog.fps = prog.frames_done / max(elapsed, 1e-3)
                    prog.eta_s = ((prog.frames_total - prog.frames_done)
                                  / max(prog.fps, 1e-3))
                    self.on_progress(prog)
                except BaseException as e:  # noqa: BLE001 — se propaga al productor
                    consumer_error.append(e)
                    return

        worker = threading.Thread(target=consumer, name="stereo-encode",
                                  daemon=True)
        worker.start()
        mode_label = ("profundidad + inpainting" if self.cfg["mode"] == "hq"
                      else "profundidad + estéreo")
        try:
            batch: list[np.ndarray] = []

            def flush(batch_list):
                if not batch_list or consumer_error:
                    return
                self._check_cancel()
                frames = np.stack(batch_list)
                t0 = time.monotonic()
                prog.stage = mode_label
                depths = depth_est.process_chunk(frames, fps)
                depths = self._normalize_depth_ema(depths)
                stage_times["depth"].append(
                    len(frames) / max(time.monotonic() - t0, 1e-3))
                prog.thumbnail = self._depth_thumbnail(depths[len(depths) // 2])
                self.on_progress(prog)
                # put con timeout: si el consumidor murió con la cola llena,
                # un put bloqueante dejaría esto colgado para siempre
                while not consumer_error:
                    try:
                        work_q.put((frames, depths), timeout=5)
                        break
                    except _queue.Full:
                        continue

            for frame in decode.decode_frames(
                    self.source, self.cfg["proc_res"], chunk.start_s,
                    chunk.duration_s, tonemap_sdr=tonemap):
                batch.append(frame)
                if len(batch) >= batch_size:
                    flush(batch)
                    batch = []
            flush(batch)
        finally:
            while True:
                try:
                    work_q.put(None, timeout=5)
                    break
                except _queue.Full:
                    if consumer_error or not worker.is_alive():
                        break
            worker.join(timeout=600)
        if consumer_error:
            raise consumer_error[0]

    def _save_calibration(self, stage_times: dict, cfg: dict) -> None:
        """Guarda fps medianos medidos → la tabla de estimaciones se vuelve real."""
        from backend.core.compute import detect_compute
        kind = detect_compute().kind
        # claves cuda: sin prefijo (compatibles con la BD estática); resto: kind:
        pre = "" if kind == "cuda" else f"{kind}:"
        upd = {}
        if stage_times["depth"]:
            key = (f"depth:{cfg['depth_model']}:{cfg['proc_res']}" if kind == "cuda"
                   else f"{kind}:depth:{cfg['depth_model']}")
            upd[key] = round(float(np.median(stage_times["depth"])), 2)
        if stage_times["stereo"]:
            key = (f"inpaint:{cfg['proc_res']}:{cfg.get('inpaint_steps', 8)}"
                   if cfg["mode"] == "hq" else f"{pre}warp:{cfg['proc_res']}")
            upd[key] = round(float(np.median(stage_times["stereo"])), 2)
        if upd:
            estimator.save_calibration(upd)

    def _output_path(self) -> Path:
        settings = config.load_settings()
        outdir = Path(settings["output_dir"])
        outdir.mkdir(parents=True, exist_ok=True)
        stem = Path(self.source).stem
        tag = estimator.OUTPUTS[self.cfg["output"]]["label"].replace(" ", ".")
        kind = "DEMO." if self.is_demo else ""
        return outdir / f"{stem}.{kind}3D.{tag}.mkv"

    # ── modo simulación (solo desarrollo de UI, sin GPU/FFmpeg) ─────────────
    def _run_simulated(self) -> Path:
        fps_video = (self.probe.get("video") or {}).get("fps") or 24.0
        frames_total = int(self.segment_duration * fps_video)
        est = estimator.estimate_one(
            self.segment_duration, fps_video, None, self.cfg["proc_res"],
            self.cfg["depth_model"], self.cfg["mode"],
            self.cfg.get("inpaint_steps", 8), self.cfg["output"])
        # tiempo simulado: el estimado (con escalador 0.3) acelerado ×600
        sim_seconds = max(est.full_seconds / 600.0, 5.0)
        prog = Progress(frames_total=frames_total, chunks_total=10,
                        stage="[SIMULACIÓN] profundidad")
        t0 = time.monotonic()
        while True:
            self._check_cancel()
            frac = min((time.monotonic() - t0) / sim_seconds, 1.0)
            prog.frames_done = int(frames_total * frac)
            prog.chunk = int(10 * frac)
            prog.fps = frames_total * frac / max(time.monotonic() - t0, 0.1)
            prog.eta_s = sim_seconds * (1 - frac)
            prog.stage = ("[SIMULACIÓN] profundidad" if frac < 0.4 else
                          "[SIMULACIÓN] síntesis estéreo" if frac < 0.8 else
                          "[SIMULACIÓN] codificando")
            self.on_progress(prog)
            if frac >= 1.0:
                break
            time.sleep(0.5)
        out_path = self._output_path().with_suffix(".SIMULACION.txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "Resultado simulado (CONVERTIDOR3D_SIMULATE=1). Sin GPU/FFmpeg no se "
            "genera vídeo real.\nConfig: " + json.dumps(self.cfg, ensure_ascii=False),
            "utf-8")
        prog.stage = "completado"
        prog.message = str(out_path)
        self.on_progress(prog)
        return out_path
