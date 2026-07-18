"""Contrato v1 de motores: streaming por LOTES numpy, nunca video completo.

Una pelicula de 2 h en 4K son ~170k frames (~1,4 TB de profundidad float32):
las interfaces de motor operan sobre lotes de N frames (N lo decide el runner
adaptativamente segun RAM, tipicamente 8-48) con contrapresion (cola de
tamano 1: como mucho dos lotes vivos). Un motor NUNCA acumula el video; si
necesita contexto temporal, mantiene su propio estado entre llamadas y lo
reinicia cuando cambia ctx.chunk_idx (los chunks son la unidad de reanudacion
y deben ser independientes).
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol, runtime_checkable

import numpy as np

API_VERSION = "1.0"


@dataclass(frozen=True)
class ChunkCtx:
    """Contexto que el runner pasa a cada llamada de motor."""
    fps: float
    chunk_idx: int
    chunks_total: int
    proc_res: str                       # '1080p' | '4k'
    cancel: Event                       # cooperativa: consultar entre sub-lotes
    ram_budget_mb: int = 0              # orientativo para sub-lotes internos
    progress: Callable[[int], None] | None = None  # frames terminados (opcional)


@runtime_checkable
class DepthEngine(Protocol):
    """(N,H,W,3) uint8 -> (N,H,W) float32 [0..1] (profundidad relativa)."""
    # Frames de contexto que el motor quisiera solapados entre lotes. Reservado:
    # el runner v1 NO implementa solape (VDA ya gestiona su ventana 32/8
    # internamente por lote); un motor que lo necesite de verdad requerira un
    # minor bump del contrato.
    temporal_window: int

    def process_chunk(self, frames: np.ndarray, ctx: ChunkCtx) -> np.ndarray: ...
    def close(self) -> None: ...


@runtime_checkable
class StereoEngine(Protocol):
    """(N,H,W,3) uint8 + (N,H,W) [0..1] -> (izquierda, derecha) uint8."""
    temporal_window: int

    def process(self, frames: np.ndarray, depths: np.ndarray,
                ctx: ChunkCtx) -> tuple[np.ndarray, np.ndarray]: ...
    def close(self) -> None: ...


@runtime_checkable
class InpaintEngine(Protocol):
    """Relleno de zonas enmascaradas: (N,H,W,3) + (N,H,W) bool -> (N,H,W,3)."""

    def fill(self, frames: np.ndarray, masks: np.ndarray,
             ctx: ChunkCtx) -> np.ndarray: ...
    def close(self) -> None: ...


@runtime_checkable
class TemporalStabilizer(Protocol):
    """Post-proceso opcional de profundidad (anti-pumping en backends por-frame)."""

    def stabilize(self, depths: np.ndarray, frames: np.ndarray,
                  ctx: ChunkCtx) -> np.ndarray: ...
    def reset(self) -> None: ...
