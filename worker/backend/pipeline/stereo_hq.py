"""Modo Calidad: splatting + inpainting de disoclusiones con StereoCrafter.

Sigue el enfoque de StereoMaster: (1) forward-splatting de la vista derecha con
máscara de oclusión, (2) inpainting con el SVD fine-tuned de TencentARC
(pasos reducidos 3-8, downscale opcional del inpainting y tiling para VRAM).

Requiere (scripts/setup.ps1 -HQ):
  - repo TencentARC/StereoCrafter en models/StereoCrafter
  - pesos HF: TencentARC/StereoCrafter + stabilityai/stable-video-diffusion-img2vid-xt-1-1
Los pesos son de licencia NO comercial (aviso en la UI).
"""
from __future__ import annotations

import numpy as np

from backend import config

SC_REPO = config.MODELS_DIR / "StereoCrafter"
SC_WEIGHTS = config.MODELS_DIR / "checkpoints" / "StereoCrafter"
SVD_WEIGHTS = config.MODELS_DIR / "checkpoints" / "stable-video-diffusion-img2vid-xt-1-1"


class StereoHQUnavailable(Exception):
    pass


def check_available() -> list[str]:
    missing = []
    try:
        import torch
        if not torch.cuda.is_available():
            missing.append("GPU CUDA (el inpainting SVD requiere GPU NVIDIA)")
    except ImportError:
        missing.append("PyTorch (pip install -r backend/requirements-ai.txt)")
    try:
        import diffusers  # noqa: F401
    except ImportError:
        missing.append("diffusers/transformers (pip install -r backend/requirements-ai.txt)")
    if not SC_REPO.exists():
        missing.append(f"Repo StereoCrafter en {SC_REPO} (scripts/setup.ps1 -HQ)")
    if not SC_WEIGHTS.exists():
        missing.append("Pesos StereoCrafter (scripts/setup.ps1 -HQ)")
    if not SVD_WEIGHTS.exists():
        missing.append("Pesos SVD img2vid-xt-1-1 (scripts/setup.ps1 -HQ)")
    return missing


class HQStereo:
    """Inpainting por chunks de vídeo cortos (VRAM acotada).

    chunk_frames y tile_num se eligen según VRAM detectada (jobs.py).
    """

    def __init__(self, divergence: float = 2.0, convergence: float = 0.5,
                 steps: int = 8, inpaint_downscale: bool = True,
                 chunk_frames: int = 24, tile_num: int = 1):
        missing = check_available()
        if missing:
            raise StereoHQUnavailable("Faltan componentes: " + "; ".join(missing))
        import sys
        import torch
        if str(SC_REPO) not in sys.path:
            sys.path.insert(0, str(SC_REPO))
        self.torch = torch
        self.steps = steps
        self.divergence = divergence
        self.convergence = convergence
        self.inpaint_downscale = inpaint_downscale
        self.chunk_frames = chunk_frames
        self.tile_num = tile_num
        self._pipeline = None  # carga perezosa en el primer chunk

    def _load_pipeline(self):
        if self._pipeline is not None:
            return
        import torch
        from diffusers import UNetSpatioTemporalConditionModel, AutoencoderKLTemporalDecoder
        from pipelines.stereo_video_inpainting import (  # del repo StereoCrafter
            StableVideoDiffusionInpaintingPipeline,
        )
        unet = UNetSpatioTemporalConditionModel.from_pretrained(
            SC_WEIGHTS / "inpainting_unet", torch_dtype=torch.float16)
        vae = AutoencoderKLTemporalDecoder.from_pretrained(
            SVD_WEIGHTS, subfolder="vae", torch_dtype=torch.float16)
        self._pipeline = StableVideoDiffusionInpaintingPipeline.from_pretrained(
            SVD_WEIGHTS, unet=unet, vae=vae, torch_dtype=torch.float16,
        ).to("cuda")
        self._pipeline.enable_model_cpu_offload()

    def _splat(self, frames: np.ndarray, depths: np.ndarray):
        """Forward-splatting de la vista derecha + máscara de oclusiones.

        Usa la operación pública del contrato de motores (engine_api.ops):
        la imagen sale con los huecos rellenos por vecino y la máscara marca
        qué zonas son desoclusión — eso es lo que inpaintará el SVD.
        """
        from engine_api.ops import DibrWarper
        warper = DibrWarper(self.divergence, self.convergence, edge_dilation=0)
        return warper.warp(frames, depths, +1)

    def process(self, frames: np.ndarray, depths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(N,H,W,3) + (N,H,W) → (izquierda=original, derecha=inpainted)."""
        self._load_pipeline()
        import torch
        warped, masks = self._splat(frames, depths)
        N, H, W, _ = frames.shape
        scale = 0.5 if self.inpaint_downscale else 1.0
        rights = []
        for start in range(0, N, self.chunk_frames):
            chunk = warped[start:start + self.chunk_frames]
            mask = masks[start:start + self.chunk_frames]
            frames_t = torch.from_numpy(chunk).permute(0, 3, 1, 2).float() / 255.0
            mask_t = torch.from_numpy(mask).unsqueeze(1).float()
            if scale != 1.0:
                frames_t = torch.nn.functional.interpolate(
                    frames_t, scale_factor=scale, mode="bilinear")
                mask_t = torch.nn.functional.interpolate(mask_t, scale_factor=scale)
            result = self._pipeline(
                frames=frames_t, frames_mask=mask_t,
                num_inference_steps=self.steps,
                tile_num=self.tile_num, decode_chunk_size=4,
            ).frames
            out = (result.clamp(0, 1) * 255).byte().permute(0, 2, 3, 1).cpu().numpy()
            if scale != 1.0:
                # recomponer a resolución completa: inpainting solo en huecos
                up = torch.nn.functional.interpolate(
                    torch.from_numpy(out).permute(0, 3, 1, 2).float(),
                    size=(H, W), mode="bilinear").byte().permute(0, 2, 3, 1).numpy()
                m = np.expand_dims(mask, -1)
                out = np.where(m, up, chunk)
            rights.append(out)
        return frames, np.concatenate(rights)

    def close(self) -> None:
        self._pipeline = None
        self.torch.cuda.empty_cache()
