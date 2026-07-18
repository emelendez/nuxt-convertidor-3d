"""Operaciones compartidas del contrato: warp DIBR con mascara de huecos.

Promociona a API publica el warp del modo rapido (antes los motores accedian
al metodo privado FastStereo._warp_one_eye — costura fragil eliminada en el
fork). Cualquier motor de estereo/relleno reutiliza esto en vez de
reimplementar el z-buffer.
"""
from __future__ import annotations

import numpy as np


class DibrWarper:
    """Warp forward DIBR por lotes con z-buffer, devolviendo la mascara de
    huecos de desoclusion (True = ningun pixel origen escribio ahi; la imagen
    devuelta los trae rellenos con el vecino escrito mas proximo por fila).
    """

    def __init__(self, divergence: float = 2.0, convergence: float = 0.5,
                 edge_dilation: int = 2):
        from backend.pipeline.stereo_fast import FastStereo
        self._fs = FastStereo(divergence, convergence, edge_dilation)
        self.divergence = divergence
        self.convergence = convergence

    def warp(self, frames: np.ndarray, depths: np.ndarray,
             sign: int) -> tuple[np.ndarray, np.ndarray]:
        """(N,H,W,3) uint8 + (N,H,W) [0..1] + ojo (-1 izq | +1 dcha) ->
        (warpeado (N,H,W,3) uint8, huecos (N,H,W) bool)."""
        return self._fs.warp_batch(frames, depths, sign)

    def max_disp_px(self, width: int) -> float:
        return self.divergence / 100.0 * width / 2.0
