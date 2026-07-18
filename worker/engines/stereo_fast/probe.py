"""Sondeo de disponibilidad del motor stereo_fast."""
from __future__ import annotations

from pathlib import Path


def probe(models_dir: Path) -> dict:
    from backend.pipeline import stereo_fast
    missing = list(stereo_fast.check_available())
    return {"available": not missing, "missing": missing, "detail": None}
