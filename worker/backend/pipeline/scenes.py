"""Segmentación en chunks alineados a cortes de escena (PySceneDetect).

Los chunks dan: consistencia temporal (la ventana de VDA no cruza cortes),
VRAM acotada y reanudación. Si PySceneDetect no está disponible, se trocea
a intervalos fijos.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_CHUNK_S = 30.0   # techo aunque la escena sea más larga
MIN_CHUNK_S = 2.0


@dataclass
class Chunk:
    index: int
    start_s: float
    duration_s: float


def _fixed_chunks(start_s: float, duration_s: float) -> list[tuple[float, float]]:
    cuts, t = [], start_s
    end = start_s + duration_s
    while t < end:
        d = min(MAX_CHUNK_S, end - t)
        cuts.append((t, d))
        t += d
    return cuts


def detect_chunks(path: str, start_s: float, duration_s: float) -> list[Chunk]:
    """Chunks alineados a escenas dentro de [start_s, start_s+duration_s]."""
    boundaries: list[float] = []
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(path, ContentDetector(threshold=27.0),
                        start_time=start_s, end_time=start_s + duration_s)
        boundaries = [s[0].get_seconds() for s in scenes]
    except Exception:
        pass  # sin PySceneDetect (o fallo): troceo fijo

    if not boundaries:
        spans = _fixed_chunks(start_s, duration_s)
    else:
        # subdividir escenas largas y fusionar micro-escenas
        spans = []
        pts = sorted({start_s, *boundaries, start_s + duration_s})
        for a, b in zip(pts, pts[1:]):
            if b - a < MIN_CHUNK_S and spans:
                prev_a, prev_d = spans[-1]
                spans[-1] = (prev_a, prev_d + (b - a))
            else:
                spans.extend(_fixed_chunks(a, b - a))
    return [Chunk(i, round(a, 3), round(d, 3)) for i, (a, d) in enumerate(spans)]
