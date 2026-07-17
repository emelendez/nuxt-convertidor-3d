"""Worker CLI del Convertidor 3D (hibrido Nitro + Python).

Lo lanza el servidor Nitro por subproceso, un proceso por trabajo:

    python cli.py --job <ruta_jobspec.json>

Envuelve `backend.pipeline.runner.RunnerContext` (el pipeline actual, intacto)
y traduce su callback `on_progress` a **lineas JSON por stdout**, que el
servidor Node parsea:

    {"type": "progress", "stage": ..., "frames_done": ..., ...}   (0..N)
    {"type": "done", "output": "<ruta>"}                          (exito)
    {"type": "cancelled"}                                         (cancelado)
    {"type": "error", "message": "..."}                           (fallo)

CANAL LIMPIO: el stdout real se reserva para ese JSON; cualquier print de las
librerias (torch, diffusers, tqdm...) se desvia a stderr para no corromperlo.

CANCELACION: el servidor escribe "cancel\\n" en stdin (o lo cierra); un hilo
vigilante activa el threading.Event `cancel` del runner -> parada limpia por
chunk (los chunks ya completados sobreviven en el workdir -> reanudable).
Tambien se atiende SIGTERM/SIGINT.

El jobspec (JSON) tiene: job_id, source, probe, cfg, segment_start,
segment_duration, is_demo, workdir, simulate.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from dataclasses import asdict
from pathlib import Path


def _setup_io():
    """Reserva el stdout real para el canal JSON y desvia el resto a stderr.

    Reconfigura ambos a UTF-8 (errors=replace) para que los acentos de los
    mensajes de etapa viajen intactos y ningun print de libreria reviente en
    terminales cp1252 de Windows.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except (AttributeError, ValueError):
            pass
    json_out = sys.stdout
    # Todo print() de librerias va ahora a stderr (no contamina el JSON).
    sys.stdout = sys.stderr
    return json_out


_JSON_OUT = _setup_io()
_EMIT_LOCK = threading.Lock()


def emit(obj: dict) -> None:
    """Escribe un objeto como una linea JSON en el canal reservado."""
    line = json.dumps(obj, ensure_ascii=False)
    with _EMIT_LOCK:
        _JSON_OUT.write(line + "\n")
        _JSON_OUT.flush()


def _load_jobspec(path: str) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def _shield_stdin():
    """Aisla el stdin real (pipe de cancelacion de Node) y pone NUL en el fd 0.

    BUG REAL cazado en el primer E2E: los subprocesos heredan el fd 0; con el
    pipe de Node como stdin, ffmpeg (sin -nostdin) se quedaba BLOQUEADO
    leyendolo (deadlock en el remux final, CPU 0, para siempre). Tras esto:
    - los hijos (ffmpeg/ffprobe) heredan NUL -> jamas se bloquean en stdin;
    - el hilo vigilante conserva el pipe real via descriptor duplicado.
    Devuelve el stream desde el que leer las ordenes de cancelacion.
    """
    try:
        saved = os.dup(0)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
        return os.fdopen(saved, "r", encoding="utf-8", errors="replace")
    except OSError:
        return sys.stdin  # sin aislamiento; mejor conservar la cancelacion


def _watch_stdin_for_cancel(stream, cancel: threading.Event) -> None:
    """Hilo vigilante: la linea 'cancel' por el canal de control activa la
    cancelacion.

    Se usa readline() (no iteracion, cuyo read-ahead retrasaria la senal).
    EOF NO cancela: evita cancelaciones espurias si el canal no queda abierto;
    el servidor pide parada con la linea 'cancel' y, de respaldo, mata el
    proceso.
    """
    try:
        while True:
            line = stream.readline()
            if line == "":  # EOF: dejar de vigilar, sin cancelar
                return
            if line.strip().lower() == "cancel":
                cancel.set()
                return
    except (ValueError, OSError):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker del Convertidor 3D")
    parser.add_argument("--job", required=True, help="Ruta al jobspec JSON")
    args = parser.parse_args()

    # Import perezoso: config.py lee las variables de entorno (CONVERTIDOR3D_DATA,
    # CONVERTIDOR3D_MODELS, ...) que Node ya inyecto antes de arrancar Python.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from backend.pipeline.runner import CancelledError, Progress, RunnerContext

    spec = _load_jobspec(args.job)
    cancel = threading.Event()

    # Aislar stdin ANTES de crear cualquier subproceso (ver _shield_stdin) y
    # vigilar el canal de control: cancelacion por la linea 'cancel' (Windows:
    # el kill duro no dispara SIGTERM de forma fiable) y por senal (Unix).
    control = _shield_stdin()
    threading.Thread(target=_watch_stdin_for_cancel, args=(control, cancel),
                     name="cancel-watch", daemon=True).start()
    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: cancel.set())
            except (ValueError, OSError):
                pass  # no siempre se puede en hilos secundarios/plataformas

    def on_progress(p: Progress) -> None:
        d = {k: v for k, v in asdict(p).items() if v is not None}
        d["type"] = "progress"
        emit(d)

    ctx = RunnerContext(
        job_id=spec["job_id"],
        source=spec["source"],
        probe=spec["probe"],
        cfg=spec["cfg"],
        segment_start=float(spec["segment_start"]),
        segment_duration=float(spec["segment_duration"]),
        is_demo=bool(spec["is_demo"]),
        workdir=Path(spec["workdir"]),
        on_progress=on_progress,
        cancel=cancel,
        simulate=bool(spec.get("simulate", False)),
    )

    try:
        out = ctx.run()
        emit({"type": "done", "output": str(out)})
        return 0
    except CancelledError:
        emit({"type": "cancelled"})
        return 0
    except Exception as e:  # noqa: BLE001 -- el error viaja a la UI como texto
        emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
