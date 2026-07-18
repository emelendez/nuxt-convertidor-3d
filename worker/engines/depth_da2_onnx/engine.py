"""Motor depth_da2_onnx: Depth Anything V2 via ONNX Runtime (DML/CPU) con
estabilizador temporal opcional.

DA2 infiere POR FRAME (no existe export ONNX de VDA): sin nada mas, la escala
de profundidad varia frame a frame y la escena "respira" en Z (pumping
estereoscopico). El estabilizador aplica una EMA por pixel guiada por
movimiento: donde la imagen apenas cambia, la profundidad se suaviza fuerte;
donde hay movimiento real, sigue al frame actual. El estado se reinicia POR
CHUNK: los chunks son la unidad de reanudacion y deben ser independientes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from engine_api import ChunkCtx

_MOTION_GAIN = 8.0     # sensibilidad del mapa de movimiento (diff 0..1)
_SMALL_W, _SMALL_H = 96, 54  # resolucion del mapa de movimiento


def _small_gray(frame: np.ndarray) -> np.ndarray:
    """(H,W,3) uint8 -> (_SMALL_H,_SMALL_W) float32 [0..1] (barato)."""
    try:
        import cv2
        g = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return cv2.resize(g, (_SMALL_W, _SMALL_H),
                          interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    except ImportError:
        ys = np.linspace(0, frame.shape[0] - 1, _SMALL_H).astype(int)
        xs = np.linspace(0, frame.shape[1] - 1, _SMALL_W).astype(int)
        return frame[ys][:, xs].mean(axis=2).astype(np.float32) / 255.0


def _upscale(m: np.ndarray, size_hw: tuple[int, int]) -> np.ndarray:
    try:
        import cv2
        return cv2.resize(m, (size_hw[1], size_hw[0]), interpolation=cv2.INTER_LINEAR)
    except ImportError:
        ys = np.linspace(0, m.shape[0] - 1, size_hw[0]).astype(int)
        xs = np.linspace(0, m.shape[1] - 1, size_hw[1]).astype(int)
        return m[ys][:, xs]


class _Da2Engine:
    temporal_window = 0

    def __init__(self, inner):
        self._inner = inner

    def process_chunk(self, frames: np.ndarray, ctx: ChunkCtx) -> np.ndarray:
        return self._inner.process_chunk(frames, ctx.fps)

    def close(self) -> None:
        self._inner.close()


class _Smoothed:
    """Decorador TemporalStabilizer sobre un DepthEngine por-frame."""
    temporal_window = 0

    def __init__(self, inner, strength: float = 0.6):
        self._inner = inner
        self._strength = min(max(strength, 0.0), 0.95)
        self._prev_d: np.ndarray | None = None
        self._prev_small: np.ndarray | None = None
        self._chunk: int | None = None

    def process_chunk(self, frames: np.ndarray, ctx: ChunkCtx) -> np.ndarray:
        d = self._inner.process_chunk(frames, ctx)
        if ctx.chunk_idx != self._chunk:   # nuevo chunk: independencia total
            self._chunk = ctx.chunk_idx
            self._prev_d = None
            self._prev_small = None
        H, W = d.shape[1], d.shape[2]
        for i in range(d.shape[0]):
            small = _small_gray(frames[i])
            if self._prev_d is not None and self._prev_small is not None:
                motion = np.clip(np.abs(small - self._prev_small) * _MOTION_GAIN,
                                 0.0, 1.0)
                alpha = self._strength * (1.0 - _upscale(motion, (H, W)))
                d[i] = alpha * self._prev_d + (1.0 - alpha) * d[i]
            self._prev_d = d[i].copy()     # EMA recursiva sobre lo ya suavizado
            self._prev_small = small
        return d

    def close(self) -> None:
        self._inner.close()


def create(cfg: dict, models_dir: Path):
    from backend.pipeline.depth_onnx import OnnxDepthEstimator
    eng = _Da2Engine(OnnxDepthEstimator(cfg.get("depth_model", "vda_s")))
    if cfg.get("depth_smooth", True):
        return _Smoothed(eng, strength=float(cfg.get("depth_smooth_strength", 0.6)))
    return eng
