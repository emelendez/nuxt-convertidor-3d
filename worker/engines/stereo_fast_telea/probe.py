"""Sondeo de disponibilidad del motor stereo_fast_telea."""
from __future__ import annotations

from pathlib import Path


def probe(models_dir: Path) -> dict:
    missing = []
    from backend.pipeline import stereo_fast
    missing += stereo_fast.check_available()
    try:
        import cv2  # noqa: F401
    except ImportError:
        missing.append("opencv-python (pip install -r worker/requirements-ai-cpu.txt)")
    return {"available": not missing, "missing": missing, "detail": None}
