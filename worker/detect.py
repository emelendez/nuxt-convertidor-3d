"""Sondeo de capacidades para el servidor Nitro.

El servidor Node no tiene torch/onnxruntime, asi que no puede saber por si mismo
si esta maquina tiene CUDA, DirectML (iGPU AMD/Intel) o solo CPU, ni que
encoder de ffmpeg funciona de verdad. Este script reutiliza la deteccion
AUTORITATIVA del pipeline Python (la misma que usaba routes.health() del
proyecto original) y la imprime como una unica linea JSON por stdout.

Node lo invoca en frio y cachea el resultado. Uso:  python detect.py

Salida (una linea JSON):
  {"compute": {...}, "components": {...}, "missing": {...}, "gpus": [...]}
o, en caso de error:  {"error": "..."}

El stdout real se reserva para ese JSON; el ruido de librerias (import de torch,
onnxruntime, etc.) se desvia a stderr para no corromperlo.
"""
from __future__ import annotations

import json
import os
import sys


def _setup_io():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except (AttributeError, ValueError):
            pass
    json_out = sys.stdout
    sys.stdout = sys.stderr  # el ruido de librerias no contamina el canal JSON
    return json_out


_JSON_OUT = _setup_io()


def _emit(obj: dict) -> None:
    _JSON_OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _JSON_OUT.flush()


def _shield_stdin() -> None:
    """Pone NUL en el fd 0: los subprocesos que lanza el sondeo (ffmpeg de
    _encoder_works, nvidia-smi, powershell) heredan stdin y con un pipe de
    Node podrian bloquearse leyendolo (mismo deadlock cazado en el mux)."""
    try:
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
    except OSError:
        pass


def main() -> int:
    _shield_stdin()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import shutil

    from backend.core import estimator
    from backend.core.compute import detect_compute
    from backend.core.gpu import detect_gpus
    from backend.pipeline import depth as depth_mod
    from backend.pipeline import encode as encode_mod
    from backend.pipeline import probe as probe_mod
    from backend.pipeline import stereo_fast, stereo_hq

    gpus = [estimator.match_gpu(g).to_dict() for g in detect_gpus()]
    compute = detect_compute()
    depth_kind, depth_missing = depth_mod.depth_backend("vda_s")
    has_ffmpeg = shutil.which("ffmpeg") is not None

    # Motores addon (worker/engines/): identidad + sondeo de cada manifest.
    import engine_registry
    from backend import config as bconfig
    engines = []
    for spec in engine_registry.load_manifests().values():
        pr = engine_registry.probe_engine(spec, bconfig.MODELS_DIR)
        weights = spec.manifest.get("weights") or []
        engines.append({
            "id": spec.id,
            "stage": spec.stage,
            "label": spec.label,
            "description": spec.manifest.get("description"),
            "available": pr["available"],
            "missing": pr["missing"],
            "detail": pr["detail"],
            "requires_compute": spec.requires_compute,
            "gated": any(w.get("gated") for w in weights),
            "licenses": sorted({w["license"] for w in weights if w.get("license")}),
            "estimator": spec.manifest.get("estimator"),
            "cfg_schema": spec.manifest.get("cfg_schema"),
        })

    _emit({
        "engines": engines,
        "compute": compute.to_dict(),
        "components": {
            "ffmpeg": has_ffmpeg,
            "ffprobe": probe_mod.ffprobe_available(),
            "nvenc": encode_mod.nvenc_available(),
            "encoder": encode_mod.pick_encoder() if has_ffmpeg else None,
            "gpu": bool(gpus),
            "depth": depth_kind,                        # 'vda' | 'onnx' | None
            "depth_vda_s": not depth_mod.check_available("vda_s"),
            "stereo_fast": not stereo_fast.check_available(),
            "stereo_hq": (not stereo_hq.check_available()) and compute.kind == "cuda",
        },
        "missing": {
            "depth": depth_missing,
            "stereo_hq": stereo_hq.check_available(),
        },
        "gpus": gpus,
    })
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- el error viaja a Node como JSON
        _emit({"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)
