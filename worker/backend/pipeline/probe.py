"""Análisis del fichero de entrada con ffprobe."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from backend import config


class ProbeError(Exception):
    pass


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _parse_fps(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: str) -> dict:
    """Metadatos del vídeo: duración, resolución, HDR, pistas y capítulos."""
    p = Path(path)
    if not p.is_file():
        raise ProbeError(f"El fichero no existe: {path}")
    if p.suffix.lower() not in config.VIDEO_EXTENSIONS:
        raise ProbeError(f"Extensión no soportada: {p.suffix}")
    if not ffprobe_available():
        raise ProbeError("ffprobe no está instalado o no está en el PATH. "
                         "Ejecuta scripts/setup.ps1 o instala FFmpeg.")
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
             "-show_streams", "-show_chapters", str(p)],
            capture_output=True, text=True, timeout=60, check=True,
            encoding="utf-8", errors="replace",
        ).stdout
    except subprocess.CalledProcessError as e:
        raise ProbeError(f"ffprobe falló: {e.stderr or e}") from e
    except subprocess.TimeoutExpired as e:
        raise ProbeError("ffprobe superó el tiempo límite (¿disco lento/red?)") from e

    data = json.loads(out)
    fmt = data.get("format", {})
    video = None
    audio_tracks, sub_tracks = [], []
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and video is None and s.get("disposition", {}).get("attached_pic", 0) != 1:
            transfer = s.get("color_transfer", "")
            video = {
                "codec": s.get("codec_name"),
                "profile": s.get("profile"),
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": _parse_fps(s.get("avg_frame_rate") or s.get("r_frame_rate", "0/1")),
                "pix_fmt": s.get("pix_fmt"),
                "bit_depth": 10 if "10" in (s.get("pix_fmt") or "") else 8,
                "hdr": transfer in ("smpte2084", "arib-std-b67"),
                "hdr_format": {"smpte2084": "HDR10/PQ", "arib-std-b67": "HLG"}.get(transfer),
                "color_primaries": s.get("color_primaries"),
            }
        elif s.get("codec_type") == "audio":
            audio_tracks.append({
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "channels": s.get("channels"),
                "language": (s.get("tags") or {}).get("language", "und"),
                "title": (s.get("tags") or {}).get("title"),
            })
        elif s.get("codec_type") == "subtitle":
            sub_tracks.append({
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "language": (s.get("tags") or {}).get("language", "und"),
                "title": (s.get("tags") or {}).get("title"),
            })
    if video is None:
        raise ProbeError("El fichero no contiene ninguna pista de vídeo")

    duration = float(fmt.get("duration", 0) or 0)
    return {
        "path": str(p),
        "filename": p.name,
        "size_bytes": p.stat().st_size,
        "duration_s": duration,
        "container": fmt.get("format_name"),
        "video": video,
        "audio_tracks": audio_tracks,
        "subtitle_tracks": sub_tracks,
        "chapters": len(data.get("chapters", [])),
        "is_4k": (video.get("width") or 0) >= 3000,
    }
