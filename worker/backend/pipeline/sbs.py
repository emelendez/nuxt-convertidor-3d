"""Composición Side-by-Side a partir de las vistas izquierda/derecha."""
from __future__ import annotations

import numpy as np

# (ancho_total, alto_total, ancho_por_ojo) — el ojo se reescala a eso
OUTPUT_GEOMETRY = {
    "hsbs_1080": (1920, 1080, 960),
    "hsbs_4k": (3840, 2160, 1920),
    "fsbs_1080": (3840, 1080, 1920),
    "fsbs_4k": (7680, 2160, 3840),
}


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    if img.shape[1] == w and img.shape[0] == h:
        return img
    try:
        import cv2
        interp = cv2.INTER_AREA if w < img.shape[1] else cv2.INTER_LANCZOS4
        return cv2.resize(img, (w, h), interpolation=interp)
    except ImportError:
        # fallback sin OpenCV: vecino más próximo con numpy (solo emergencia)
        ys = (np.linspace(0, img.shape[0] - 1, h)).astype(int)
        xs = (np.linspace(0, img.shape[1] - 1, w)).astype(int)
        return img[ys][:, xs]


def compose_sbs(left: np.ndarray, right: np.ndarray, output: str) -> np.ndarray:
    """(H,W,3) + (H,W,3) → frame SBS uint8 según la geometría de salida."""
    total_w, total_h, eye_w = OUTPUT_GEOMETRY[output]
    l = _resize(left, eye_w, total_h)
    r = _resize(right, eye_w, total_h)
    return np.concatenate([l, r], axis=1)
