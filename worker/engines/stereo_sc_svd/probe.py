"""Sondeo de disponibilidad del motor stereo_sc_svd."""
from __future__ import annotations

from pathlib import Path


def probe(models_dir: Path) -> dict:
    from backend.pipeline import stereo_hq
    missing = list(stereo_hq.check_available())
    return {"available": not missing, "missing": missing, "detail": None}
