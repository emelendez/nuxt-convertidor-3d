"""Motor stereo_fast: adaptador de backend.pipeline.stereo_fast.FastStereo."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from engine_api import ChunkCtx


class _FastEngine:
    temporal_window = 0

    def __init__(self, inner):
        self._inner = inner

    def process(self, frames: np.ndarray, depths: np.ndarray,
                ctx: ChunkCtx) -> tuple[np.ndarray, np.ndarray]:
        return self._inner.process(frames, depths)

    def close(self) -> None:
        pass


def create(cfg: dict, models_dir: Path):
    from backend.pipeline.stereo_fast import FastStereo
    return _FastEngine(FastStereo(cfg.get("divergence", 2.0),
                                  cfg.get("convergence", 0.5)))
