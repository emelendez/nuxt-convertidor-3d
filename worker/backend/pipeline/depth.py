"""Estimación de profundidad con Video Depth Anything (S/B/L).

El repositorio oficial se clona en models/Video-Depth-Anything (setup.ps1) y
los checkpoints en models/checkpoints/. Se usa su API de modelo directamente
(no run.py) para poder alimentar frames desde el pipe de ffmpeg sin decord.

Consistencia temporal: infer_video_depth del repo aplica ventana deslizante de
32 frames con solapamiento de 8 + keyframes; aquí procesamos por chunks de
escena y delegamos la ventana al método del modelo.
"""
from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from backend import config

VDA_REPO = config.MODELS_DIR / "Video-Depth-Anything"
CHECKPOINTS = {
    "vda_s": config.MODELS_DIR / "checkpoints" / "video_depth_anything_vits.pth",
    "vda_b": config.MODELS_DIR / "checkpoints" / "video_depth_anything_vitb.pth",
    "vda_l": config.MODELS_DIR / "checkpoints" / "video_depth_anything_vitl.pth",
}
ENCODER = {"vda_s": "vits", "vda_b": "vitb", "vda_l": "vitl"}
MODEL_CONFIG = {
    "vits": {"features": 64, "out_channels": [48, 96, 192, 384]},
    "vitb": {"features": 128, "out_channels": [96, 192, 384, 768]},
    "vitl": {"features": 256, "out_channels": [256, 512, 1024, 1024]},
}


class DepthUnavailable(Exception):
    pass


def check_available(model: str) -> list[str]:
    """Lista de componentes que faltan para poder inferir profundidad."""
    missing = []
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("PyTorch (pip install -r backend/requirements-ai.txt)")
    if not VDA_REPO.exists():
        missing.append(f"Repo Video-Depth-Anything en {VDA_REPO} (scripts/setup.ps1)")
    ckpt = CHECKPOINTS.get(model)
    if ckpt and not ckpt.exists():
        missing.append(f"Checkpoint {ckpt.name} (scripts/setup.ps1 -Weights)")
    return missing


class DepthEstimator:
    """Carga perezosa del modelo; process() acepta frames uint8 HxWx3."""

    def __init__(self, model: str, input_size: int = 518, window: int = 32):
        missing = check_available(model)
        if missing:
            raise DepthUnavailable("Faltan componentes: " + "; ".join(missing))
        import sys
        import torch
        if str(VDA_REPO) not in sys.path:
            sys.path.insert(0, str(VDA_REPO))
        from video_depth_anything.video_depth import VideoDepthAnything

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.input_size = input_size
        self.window = window
        encoder = ENCODER[model]
        self.model = VideoDepthAnything(encoder=encoder, **MODEL_CONFIG[encoder])
        state = torch.load(CHECKPOINTS[model], map_location="cpu")
        self.model.load_state_dict(state, strict=True)
        self.model = self.model.to(self.device).eval()
        if self.device == "cuda":
            self.model = self.model.half()

    def process_chunk(self, frames: np.ndarray, fps: float) -> np.ndarray:
        """frames: (N,H,W,3) uint8 → profundidad relativa (N,H,W) float32 [0..1].

        Usa infer_video_depth del repo (gestiona la ventana 32/8 internamente).
        """
        depths, _ = self.model.infer_video_depth(
            frames, target_fps=fps, input_size=self.input_size,
            device=self.device, fp32=False,
        )
        d = np.asarray(depths, dtype=np.float32)
        # normalización por chunk a [0..1]; VDA da profundidad relativa
        dmin, dmax = float(d.min()), float(d.max())
        if dmax - dmin > 1e-6:
            d = (d - dmin) / (dmax - dmin)
        return d

    def close(self) -> None:
        del self.model
        gc.collect()
        if self.device == "cuda":
            self.torch.cuda.empty_cache()


# ── selección de implementación según backend ──────────────────────────────
def depth_backend(model: str) -> tuple[str | None, list[str]]:
    """('vda'|'onnx'|None, piezas_que_faltan) para el modelo dado."""
    vda_missing = check_available(model)
    if not vda_missing:
        try:
            import torch
            if torch.cuda.is_available():
                return "vda", []
        except ImportError:
            pass
    from backend.pipeline import depth_onnx
    onnx_missing = depth_onnx.check_available(model)
    if not onnx_missing:
        return "onnx", []
    return None, vda_missing + onnx_missing


def create_depth_estimator(model: str, window: int = 32):
    """VDA con CUDA si es posible; si no, Depth Anything V2 ONNX (DML/CPU)."""
    kind, missing = depth_backend(model)
    if kind == "vda":
        return DepthEstimator(model, window=window)
    if kind == "onnx":
        from backend.pipeline.depth_onnx import OnnxDepthEstimator
        return OnnxDepthEstimator(model)
    raise DepthUnavailable("Faltan componentes: " + "; ".join(missing))
