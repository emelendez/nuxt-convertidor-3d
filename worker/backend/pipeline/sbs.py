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


def _sharpen_h(img: np.ndarray, amount: float, radius: float) -> np.ndarray:
    """Unsharp mask ANISOTROPICO (solo horizontal): realza el detalle horizontal
    sin tocar el vertical. Compensa la perdida de resolucion horizontal del
    Half-SBS (cada ojo se comprime a la mitad de ancho y la TV lo reescala
    despues). El desenfoque usa un kernel gaussiano de altura 1 (kx x 1), asi
    que la nitidez no afecta a las lineas horizontales del panel FPR. No-op sin
    OpenCV."""
    if amount <= 0:
        return img
    try:
        import cv2
    except ImportError:
        return img
    sigma = max(radius, 0.1)
    k = max(3, int(sigma * 6) | 1)                       # tamano impar ~6 sigma
    blur = cv2.GaussianBlur(img, (k, 1), sigmaX=sigma, sigmaY=0)
    return cv2.addWeighted(img, 1.0 + amount, blur, -amount, 0)


def compose_sbs(left: np.ndarray, right: np.ndarray, output: str,
                sharpen: float = 0.0, sharpen_radius: float = 1.0) -> np.ndarray:
    """(H,W,3) + (H,W,3) → frame SBS uint8 según la geometría de salida.

    Con sharpen>0 aplica nitidez horizontal a cada ojo DESPUES del reescalado
    por-ojo (que es donde se pierde la resolucion horizontal)."""
    total_w, total_h, eye_w = OUTPUT_GEOMETRY[output]
    l = _resize(left, eye_w, total_h)
    r = _resize(right, eye_w, total_h)
    if sharpen > 0:
        l = _sharpen_h(l, sharpen, sharpen_radius)
        r = _sharpen_h(r, sharpen, sharpen_radius)
    return np.concatenate([l, r], axis=1)
