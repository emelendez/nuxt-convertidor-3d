"""Profundidad sin CUDA: Depth Anything V2 (imagen) vía ONNX Runtime.

No existe export ONNX de Video Depth Anything (la atención temporal lo impide),
así que en los backends dml/cpu se infiere POR FRAME con Depth Anything V2 y la
consistencia temporal se aproxima con el suavizado EMA + reset por escena del
runner (mismo enfoque que iw3). Calidad temporal algo menor que VDA; suficiente
para SBS.

Modelos (descarga scripts/setup.ps1 -DML, de onnx-community en Hugging Face):
  models/checkpoints/onnx/da2_s.onnx  (Small, Apache-2.0  → uso libre)
  models/checkpoints/onnx/da2_b.onnx  (Base,  CC-BY-NC-4.0)
  models/checkpoints/onnx/da2_l.onnx  (Large, CC-BY-NC-4.0)
Proveedores: DmlExecutionProvider (GPU DX12, p. ej. Radeon integrada) →
CPUExecutionProvider.
"""
from __future__ import annotations

import numpy as np

from backend import config

ONNX_DIR = config.MODELS_DIR / "checkpoints" / "onnx"
MODEL_FILES = {"vda_s": "da2_s.onnx", "vda_b": "da2_b.onnx", "vda_l": "da2_l.onnx"}
INPUT_SIZE = 518  # fijo: DML recompila con formas dinámicas
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)


class DepthOnnxUnavailable(Exception):
    pass


def check_available(model: str) -> list[str]:
    missing = []
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        missing.append("onnxruntime (pip install onnxruntime-directml)")
    path = ONNX_DIR / MODEL_FILES[model]
    if not path.exists():
        missing.append(f"Modelo {path.name} (scripts/setup.ps1 -DML)")
    return missing


def active_provider() -> str | None:
    try:
        import onnxruntime as ort
        provs = ort.get_available_providers()
        return "dml" if "DmlExecutionProvider" in provs else "cpu"
    except ImportError:
        return None


class OnnxDepthEstimator:
    """API compatible con pipeline.depth.DepthEstimator (process_chunk/close)."""

    def __init__(self, model: str, input_size: int = INPUT_SIZE, window: int = 0):
        missing = check_available(model)
        if missing:
            raise DepthOnnxUnavailable("Faltan componentes: " + "; ".join(missing))
        import onnxruntime as ort
        self.input_size = input_size
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = []
        if "DmlExecutionProvider" in ort.get_available_providers():
            providers.append("DmlExecutionProvider")
        providers.append("CPUExecutionProvider")
        self.session = ort.InferenceSession(str(ONNX_DIR / MODEL_FILES[model]),
                                            sess_options=opts, providers=providers)
        self.provider = self.session.get_providers()[0]
        self.input_name = self.session.get_inputs()[0].name
        self.input_type = self.session.get_inputs()[0].type  # fp32 o fp16

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        try:
            import cv2
            img = cv2.resize(frame, (self.input_size, self.input_size),
                             interpolation=cv2.INTER_AREA)
        except ImportError:
            ys = np.linspace(0, frame.shape[0] - 1, self.input_size).astype(int)
            xs = np.linspace(0, frame.shape[1] - 1, self.input_size).astype(int)
            img = frame[ys][:, xs]
        x = (img.astype(np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
        x = x.transpose(2, 0, 1)[None]
        if "float16" in self.input_type:
            x = x.astype(np.float16)
        return x

    def process_chunk(self, frames: np.ndarray, fps: float = 0.0) -> np.ndarray:
        """(N,H,W,3) uint8 → (N,H,W) float32 [0..1] (por frame, sin ventana)."""
        N, H, W, _ = frames.shape
        out = np.empty((N, H, W), np.float32)
        for i in range(N):
            d = self.session.run(None, {self.input_name: self._preprocess(frames[i])})[0]
            d = np.squeeze(d).astype(np.float32)        # (518,518) o (1,518,518)
            try:
                import cv2
                d = cv2.resize(d, (W, H), interpolation=cv2.INTER_LINEAR)
            except ImportError:
                ys = np.linspace(0, d.shape[0] - 1, H).astype(int)
                xs = np.linspace(0, d.shape[1] - 1, W).astype(int)
                d = d[ys][:, xs]
            out[i] = d
        lo, hi = float(out.min()), float(out.max())
        if hi - lo > 1e-6:
            out = (out - lo) / (hi - lo)
        return out

    def close(self) -> None:
        self.session = None
