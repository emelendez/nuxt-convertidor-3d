"""Motor stereo_sc_svd: adaptador de backend.pipeline.stereo_hq.HQStereo."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from engine_api import ChunkCtx


class _SvdEngine:
    temporal_window = 0

    def __init__(self, inner):
        self._inner = inner

    def process(self, frames: np.ndarray, depths: np.ndarray,
                ctx: ChunkCtx) -> tuple[np.ndarray, np.ndarray]:
        return self._inner.process(frames, depths)

    def close(self) -> None:
        self._inner.close()


def create(cfg: dict, models_dir: Path):
    from backend.pipeline.stereo_hq import HQStereo
    return _SvdEngine(HQStereo(
        cfg.get("divergence", 2.0), cfg.get("convergence", 0.5),
        steps=cfg.get("inpaint_steps", 8),
        inpaint_downscale=cfg.get("inpaint_downscale", True)))
