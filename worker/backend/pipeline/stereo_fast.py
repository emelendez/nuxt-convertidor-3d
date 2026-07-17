"""Modo rápido: síntesis estéreo por forward-warp (DIBR) en PyTorch puro.

Genera vista izquierda y derecha desplazando píxeles según disparidad derivada
de la profundidad (convenio iw3: divergencia en % del ancho, convergencia 0-1
sitúa el plano de pantalla). Los huecos de disoclusión se rellenan con el
vecino escrito más próximo por fila (sin difusión: rápido, artefactos leves
en bordes).

Sin extensiones CUDA propias: z-buffer por ``scatter_reduce(amax)`` sobre una
clave entera ``disparidad_cuantizada * W + columna_origen`` — el píxel más
cercano gana el conflicto y la columna origen se recupera con un módulo.
Todo el sub-lote se procesa vectorizado y los colores viajan como uint8
(solo se mueven índices; nunca se convierte la imagen a float).
"""
from __future__ import annotations

import numpy as np

# Frames por sub-lote de warp: limita la memoria pico de los tensores de
# índices int64 (~150 MB por frame y ojo a 1080p contando temporales). En
# equipos de 16 GB compartidos con la iGPU el commit es escaso: mantener bajo.
_WARP_BATCH = 2
# Niveles de cuantización de la disparidad para la clave del z-buffer.
# 2·max_disp/65536 ≈ 0,0006 px por nivel a 1080p: muy por debajo del propio
# redondeo a píxel entero del warp.
_QLEVELS = 65536


class StereoFastUnavailable(Exception):
    pass


def check_available() -> list[str]:
    try:
        import torch  # noqa: F401
        return []
    except ImportError:
        return ["PyTorch (pip install -r backend/requirements-ai.txt)"]


class FastStereo:
    def __init__(self, divergence: float = 2.0, convergence: float = 0.5,
                 edge_dilation: int = 2):
        missing = check_available()
        if missing:
            raise StereoFastUnavailable("Faltan componentes: " + "; ".join(missing))
        import torch
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.divergence = divergence
        self.convergence = convergence
        self.edge_dilation = edge_dilation

    def _warp(self, imgs, disp, sign: int, max_disp_px: float):
        """Warp vectorizado de un sub-lote.

        imgs (B,H,W,C) cualquier dtype, disp (B,H,W) float en píxeles →
        (warpeado (B,H,W,C) mismo dtype, written (B,H,W) bool).
        """
        torch = self.torch
        B, H, W, C = imgs.shape
        dev = imgs.device
        xs = torch.arange(W, device=dev, dtype=torch.int32)

        target = torch.round(xs + sign * disp).long().clamp_(0, W - 1)

        # Clave del z-buffer: disparidad con signo cuantizada (mayor = más
        # cerca, porque la profundidad es inversa) con la columna origen en
        # los bits bajos como desempate. amax deja ganar al más cercano.
        scale = (_QLEVELS - 1) * 0.5 / max(max_disp_px, 1e-6)
        # +0.5 y truncado a int = redondeo (disp*scale+offset nunca baja de -1)
        prio = (disp * scale + ((_QLEVELS - 1) * 0.5 + 0.5)).to(torch.int32)
        key = prio.clamp_(0, _QLEVELS - 1).mul_(W).add_(xs)

        rows = torch.arange(B * H, device=dev).view(B, H, 1) * W
        buf = torch.full((B * H * W,), -1, dtype=torch.int32, device=dev)
        buf.scatter_reduce_(0, (target + rows).view(-1), key.view(-1),
                            reduce="amax")
        buf = buf.view(B, H, W)
        written = buf >= 0
        # Columna origen de cada píxel escrito; en los no escritos, identidad
        # (fallback para huecos en los extremos de fila sin vecino escrito).
        src_x = torch.where(written, buf.remainder(W), xs)

        # Relleno de huecos: posición escrita más próxima por la izquierda y
        # por la derecha (vía cummax), eligiendo la más cercana.
        left_pos = torch.where(written, xs, xs.new_zeros(())).cummax(-1).values
        right_pos = (W - 1) - torch.where(written, (W - 1) - xs, xs.new_zeros(())) \
            .flip(-1).cummax(-1).values.flip(-1)
        use_right = (right_pos - xs) < (xs - left_pos)
        fill_pos = torch.where(use_right, right_pos, left_pos)
        final_col = torch.where(written, xs, fill_pos).long()

        src = src_x.gather(-1, final_col).long().unsqueeze(-1).expand(B, H, W, C)
        return imgs.gather(2, src), written

    def _dilate_fg(self, d):
        """Dilata el primer plano para tapar halos en bordes de objetos.

        Máximo separable por desplazamientos: idéntico a max_pool2d de kernel
        2r+1 (stride 1) pero un orden de magnitud más rápido en CPU.
        """
        torch = self.torch
        for _ in range(self.edge_dilation):
            d = torch.maximum(d, torch.maximum(
                torch.cat([d[..., :1], d[..., :-1]], -1),
                torch.cat([d[..., 1:], d[..., -1:]], -1)))
            d = torch.maximum(d, torch.maximum(
                torch.cat([d[:, :1], d[:, :-1]], 1),
                torch.cat([d[:, 1:], d[:, -1:]], 1)))
        return d

    def _warp_one_eye(self, img, disp, sign: int):
        """img (H,W,3) float, disp (H,W) float en píxeles → vista warpeada.

        Compatibilidad con stereo_hq._splat (que detecta los huecos aparte).
        """
        W = img.shape[1]
        max_disp_px = self.divergence / 100.0 * W / 2.0
        out, _ = self._warp(img[None], disp[None], sign, max_disp_px)
        return out[0]

    def process(self, frames: np.ndarray, depths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(N,H,W,3) uint8 + (N,H,W) [0..1] → (izquierda, derecha) uint8."""
        torch = self.torch
        N, H, W, _ = frames.shape
        max_disp_px = self.divergence / 100.0 * W / 2.0  # mitad por ojo
        left = np.empty_like(frames)
        right = np.empty_like(frames)
        with torch.no_grad():
            for i0 in range(0, N, _WARP_BATCH):
                i1 = min(i0 + _WARP_BATCH, N)
                imgs = torch.from_numpy(frames[i0:i1]).to(self.device)
                d = torch.from_numpy(depths[i0:i1]).to(self.device).float()
                if self.edge_dilation > 0:
                    d = self._dilate_fg(d)
                disp = (d - self.convergence) * max_disp_px
                l, _ = self._warp(imgs, disp, -1, max_disp_px)
                r, _ = self._warp(imgs, disp, +1, max_disp_px)
                left[i0:i1] = l.cpu().numpy()
                right[i0:i1] = r.cpu().numpy()
        return left, right
