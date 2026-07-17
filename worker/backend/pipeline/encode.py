"""Codificación HEVC por pipe hacia ffmpeg (NVENC → AMF → libx265)."""
from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import numpy as np

from backend.pipeline.sbs import OUTPUT_GEOMETRY


class EncodeError(Exception):
    pass


# Bitrates VBR objetivo por salida (HEVC 10-bit, contenido película)
BITRATE = {"hsbs_1080": "12M", "fsbs_1080": "20M", "hsbs_4k": "40M", "fsbs_4k": "70M"}


def _ffmpeg_encoders() -> str:
    if not shutil.which("ffmpeg"):
        return ""
    try:
        return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=15).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _encoder_works(encoder: str) -> bool:
    """Prueba real: estar compilado en ffmpeg no implica que el hardware exista."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=black:s=256x256:d=0.1", "-frames:v", "1",
             "-c:v", encoder, "-f", "null", "-"],
            capture_output=True, timeout=30)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@functools.lru_cache(maxsize=1)
def nvenc_available() -> bool:
    return "hevc_nvenc" in _ffmpeg_encoders() and _encoder_works("hevc_nvenc")


@functools.lru_cache(maxsize=1)
def pick_encoder() -> str:
    """Cascada: NVENC (NVIDIA) → AMF (AMD, HEVC 8-bit) → libx265 (CPU, 10-bit)."""
    encoders = _ffmpeg_encoders()
    if "hevc_nvenc" in encoders and _encoder_works("hevc_nvenc"):
        return "hevc_nvenc"
    if "hevc_amf" in encoders and _encoder_works("hevc_amf"):
        return "hevc_amf"
    return "libx265"


# args de códec y pix_fmt por encoder. Nota: AMF en VCN 2.x (Vega/Renoir)
# NO codifica HEVC 10-bit → nv12 (8-bit); x265 con preset rápido en CPU.
def _codec_args(encoder: str, output: str, cpu_threads: int = 0) -> tuple[list[str], str]:
    if encoder == "hevc_nvenc":
        return (["-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq",
                 "-rc", "vbr", "-b:v", BITRATE[output],
                 "-maxrate", BITRATE[output].replace("M", "") + "M"], "p010le")
    if encoder == "hevc_amf":
        return (["-c:v", "hevc_amf", "-usage", "transcoding", "-quality",
                 "quality", "-rc", "vbr_peak", "-b:v", BITRATE[output]], "nv12")
    preset = "fast" if (cpu_threads or 8) >= 12 else "faster"
    return (["-c:v", "libx265", "-preset", preset, "-crf", "19",
             "-x265-params", "log-level=error"], "yuv420p10le")


class SegmentEncoder:
    """Codifica un segmento (chunk) a un .mkv temporal recibiendo frames por stdin."""

    def __init__(self, out_path: Path, output: str, fps: float,
                 encoder: str | None = None, cpu_threads: int = 0):
        if not shutil.which("ffmpeg"):
            raise EncodeError("ffmpeg no está instalado")
        self.out_path = out_path
        total_w, total_h, _ = OUTPUT_GEOMETRY[output]
        self.frame_bytes = total_w * total_h * 3
        self.encoder = encoder or pick_encoder()
        codec, pix_fmt = _codec_args(self.encoder, output, cpu_threads)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{total_w}x{total_h}", "-r", f"{fps:.6f}", "-i", "pipe:0",
               *codec, "-pix_fmt", pix_fmt,
               "-color_primaries", "bt709", "-color_trc", "bt709",
               "-colorspace", "bt709", str(out_path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stderr=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        try:
            self.proc.stdin.write(frame.tobytes())
        except BrokenPipeError as e:
            stderr = self.proc.stderr.read().decode(errors="replace")
            raise EncodeError(f"El codificador terminó inesperadamente: {stderr[-800:]}") from e

    def close(self) -> None:
        self.proc.stdin.close()
        stderr = self.proc.stderr.read().decode(errors="replace")
        if self.proc.wait() != 0:
            raise EncodeError(f"ffmpeg encode falló: {stderr[-800:]}")


def concat_segments(segments: list[Path], out_path: Path) -> None:
    """Concatena chunks .mkv sin recodificar (concat demuxer)."""
    lst = out_path.with_suffix(".txt")
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments), "utf-8")
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(lst), "-c", "copy", str(out_path)],
            capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            raise EncodeError(f"Concatenación falló: {r.stderr[-800:]}")
    finally:
        lst.unlink(missing_ok=True)


def make_preview(mkv_path: Path, preview_path: Path, h264: bool = False) -> None:
    """MP4 de previsualización para el navegador (hvc1 o H.264 fallback)."""
    if h264:
        codec = ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-vf", "scale=-2:1080"]
    else:
        codec = ["-c:v", "copy", "-tag:v", "hvc1"]
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mkv_path),
         *codec, "-an", "-movflags", "+faststart", str(preview_path)],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise EncodeError(f"Preview falló: {r.stderr[-800:]}")


def _duration_s(src: Path) -> float | None:
    """Duración en segundos vía ffprobe; None si no se puede determinar."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(src)],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def make_output_preview(src: Path, out: Path, clip_s: float = 45.0) -> None:
    """Clip corto H.264 de un fichero de salida ya convertido, para previsualizar
    en el navegador (los MKV finales son HEVC, que el navegador no reproduce).

    Conserva el layout SBS (el renderer lo divide en izquierda/derecha para
    anaglifo/entrelazado). Escala a 1080 de alto, sin audio, faststart para
    streaming. En películas largas arranca a ~15 % para evitar intros/negros."""
    start = 0.0
    dur = _duration_s(src)
    if dur and dur > clip_s + 5:
        start = min(dur * 0.15, max(dur - clip_s, 0.0))
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start > 0:
        args += ["-ss", f"{start:.2f}"]
    args += ["-i", str(src), "-t", f"{clip_s:.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-vf", "scale=-2:1080",
             "-an", "-movflags", "+faststart", str(out)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise EncodeError(f"Preview falló: {r.stderr[-800:]}")
