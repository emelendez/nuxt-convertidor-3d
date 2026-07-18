"""Sondeo de disponibilidad del motor depth_vda."""
from __future__ import annotations

from pathlib import Path


def probe(models_dir: Path) -> dict:
    from backend.pipeline import depth
    missing = list(depth.check_available("vda_s"))
    try:
        import torch
        if not torch.cuda.is_available():
            missing.append("GPU CUDA (torch.cuda no disponible)")
    except ImportError:
        pass  # ya reportado por check_available
    return {"available": not missing, "missing": missing, "detail": None}
