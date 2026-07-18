"""Motor depth_vda: adaptador de backend.pipeline.depth.DepthEstimator al
contrato engine_api v1."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from engine_api import ChunkCtx


class _VdaEngine:
    # VDA gestiona su ventana temporal 32/8 internamente por lote; el runner
    # no necesita solapar lotes por el (ver nota en engine_api.v1).
    temporal_window = 0

    def __init__(self, inner):
        self._inner = inner

    def process_chunk(self, frames: np.ndarray, ctx: ChunkCtx) -> np.ndarray:
        return self._inner.process_chunk(frames, ctx.fps)

    def close(self) -> None:
        self._inner.close()


def create(cfg: dict, models_dir: Path):
    from backend.pipeline.depth import DepthEstimator
    window = 32 if cfg.get("vram_ok", True) else 16
    return _VdaEngine(DepthEstimator(cfg.get("depth_model", "vda_s"), window=window))
