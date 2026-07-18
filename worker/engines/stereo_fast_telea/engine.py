"""Motor stereo_fast_telea ("HQ-lite"): warp DIBR + relleno Telea.

Con divergence=2.0 los huecos de desoclusion son bandas de <=~19 px a 1080p
pegadas a bordes de profundidad. El relleno por vecino del modo rapido las
tapa repitiendo la ultima columna visible (streaking); aqui se rellenan con
cv2.inpaint(TELEA) (difusion desde el borde: mas suave y sin rayas). En
Half-SBS (downscale horizontal x2) el resultado queda cerca del inpainting
SVD sin CUDA ni pesos gated. Coste: ~ms por frame en CPU.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from engine_api import ChunkCtx
from engine_api.ops import DibrWarper


class TeleaStereo:
    temporal_window = 0

    def __init__(self, divergence: float, convergence: float, radius: int = 3):
        self._warper = DibrWarper(divergence, convergence, edge_dilation=2)
        self._radius = int(radius)

    def process(self, frames: np.ndarray, depths: np.ndarray,
                ctx: ChunkCtx) -> tuple[np.ndarray, np.ndarray]:
        import cv2
        left, lholes = self._warper.warp(frames, depths, -1)
        right, rholes = self._warper.warp(frames, depths, +1)
        for i in range(frames.shape[0]):
            if ctx.cancel.is_set():
                break   # el runner comprueba y lanza CancelledError entre lotes
            if lholes[i].any():
                left[i] = cv2.inpaint(left[i], lholes[i].astype(np.uint8),
                                      self._radius, cv2.INPAINT_TELEA)
            if rholes[i].any():
                right[i] = cv2.inpaint(right[i], rholes[i].astype(np.uint8),
                                       self._radius, cv2.INPAINT_TELEA)
        return left, right

    def close(self) -> None:
        pass


def create(cfg: dict, models_dir: Path):
    return TeleaStereo(cfg.get("divergence", 2.0), cfg.get("convergence", 0.5),
                       radius=int(cfg.get("telea_radius", 3)))
