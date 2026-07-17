"""Decodificación por pipe ffmpeg → frames RGB en numpy (sin ficheros intermedios)."""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator

import numpy as np

PROC_RES = {"1080p": (1920, 1080), "4k": (3840, 2160)}


class DecodeError(Exception):
    pass


def _build_cmd(path: str, width: int, height: int,
               start_s: float | None, duration_s: float | None,
               hwaccel: str | None, tonemap_sdr: bool) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start_s:
        cmd += ["-ss", f"{start_s:.3f}"]  # seek de entrada: rápido, por keyframe
    if hwaccel:
        cmd += ["-hwaccel", hwaccel]  # 'cuda' (NVDEC) o 'd3d11va' (AMD/Intel)
    cmd += ["-i", path]
    if duration_s:
        cmd += ["-t", f"{duration_s:.3f}"]
    filters = []
    if tonemap_sdr:
        # HDR10/HLG → SDR BT.709 (hable); requiere zscale (build full de ffmpeg)
        filters.append(
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=hable,zscale=t=bt709:m=bt709:r=tv")
    filters.append(f"scale={width}:{height}:flags=lanczos")
    cmd += ["-vf", ",".join(filters), "-map", "0:v:0", "-an", "-sn",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    return cmd


def decode_frames(path: str, proc_res: str, start_s: float | None = None,
                  duration_s: float | None = None,
                  hwaccel: str | None = "auto",
                  tonemap_sdr: bool = False) -> Iterator[np.ndarray]:
    """Genera frames HxWx3 uint8. Reintenta por software si falla el hwaccel."""
    if not shutil.which("ffmpeg"):
        raise DecodeError("ffmpeg no está instalado o no está en el PATH")
    width, height = PROC_RES[proc_res]
    frame_bytes = width * height * 3

    if hwaccel == "auto":
        from backend.core.compute import detect_compute
        hwaccel = {"cuda": "cuda", "dml": "d3d11va", "cpu": None}[detect_compute().kind]

    for attempt_hw in ([hwaccel, None] if hwaccel else [None]):
        cmd = _build_cmd(path, width, height, start_s, duration_s,
                         attempt_hw, tonemap_sdr)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=frame_bytes * 4)
        got_any = False
        try:
            while True:
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                got_any = True
                yield np.frombuffer(buf, np.uint8).reshape(height, width, 3)
        finally:
            proc.stdout.close()
            stderr = proc.stderr.read().decode(errors="replace")
            proc.wait()
        if got_any or proc.returncode == 0:
            return
        # NVDEC falló sin producir nada → reintento por software
        if not attempt_nvdec:
            raise DecodeError(f"ffmpeg no pudo decodificar: {stderr[-800:]}")


def extract_thumbnails(path: str, timestamps: list[float], width: int = 320) -> list[bytes]:
    """Miniaturas JPEG en los timestamps dados (para el selector de demo)."""
    if not shutil.which("ffmpeg"):
        raise DecodeError("ffmpeg no está instalado")
    thumbs = []
    for ts in timestamps:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{ts:.3f}",
             "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2",
             "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"],
            capture_output=True, timeout=30,
        )
        thumbs.append(out.stdout if out.returncode == 0 else b"")
    return thumbs
