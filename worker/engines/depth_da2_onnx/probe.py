"""Sondeo de disponibilidad del motor depth_da2_onnx."""
from __future__ import annotations

from pathlib import Path


def probe(models_dir: Path) -> dict:
    from backend.pipeline import depth_onnx
    missing = list(depth_onnx.check_available("vda_s"))
    provider = depth_onnx.active_provider()
    detail = {"dml": "DirectML", "cpu": "CPU"}.get(provider or "", None)
    return {"available": not missing, "missing": missing, "detail": detail}
