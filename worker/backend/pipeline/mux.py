"""Remux final: vídeo 3D + audio/subtítulos/capítulos del original + stereo_mode.

Detalle que ninguna herramienta del estado del arte hace bien (iw3 pierde
subtítulos y capítulos): aquí se copian TODAS las pistas del MKV original.
El flag Matroska stereo_mode no garantiza la auto-conmutación en TVs LG
(activación manual con el botón 3D), pero ayuda en Kodi/Plex/PC.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class MuxError(Exception):
    pass


def _build_cmd(video_path: Path, source_path: Path, out_path: Path,
               is_demo: bool, demo_start_s: float | None,
               demo_duration_s: float | None, include_subs: bool) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(video_path)]
    if is_demo and demo_start_s is not None:
        # para la demo, cortar el audio del original en el mismo punto
        cmd += ["-ss", f"{demo_start_s:.3f}"]
    cmd += ["-i", str(source_path), "-map", "0:v:0", "-map", "1:a?"]
    if is_demo:
        # Demo: -ss + copy de audio deja los PTS desplazados (audio desincronizado
        # y duración inflada). Recodificar el audio (clip corto: coste trivial)
        # resetea los timestamps; sin subtítulos ni capítulos en demos.
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-map_chapters", "-1"]
        if demo_duration_s:
            cmd += ["-t", f"{demo_duration_s:.3f}"]
    else:
        if include_subs:
            cmd += ["-map", "1:s?", "-c:s", "copy"]
        cmd += ["-c:v", "copy", "-c:a", "copy", "-map_chapters", "1"]
    cmd += ["-metadata:s:v:0", "stereo_mode=left_right",
            "-metadata", f"title={out_path.stem}", str(out_path)]
    return cmd


def mux_final(video_path: Path, source_path: Path, out_path: Path,
              output: str, is_demo: bool = False,
              demo_start_s: float | None = None,
              demo_duration_s: float | None = None) -> None:
    """Combina el vídeo 3D con las pistas del original (SBS → left_right)."""
    if not shutil.which("ffmpeg"):
        raise MuxError("ffmpeg no está instalado")
    cmd = _build_cmd(video_path, source_path, out_path, is_demo, demo_start_s,
                     demo_duration_s, include_subs=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode == 0:
        return
    # Algunos códecs de subtítulos no admiten copy en MKV → reintento sin subs
    cmd = _build_cmd(video_path, source_path, out_path, is_demo, demo_start_s,
                     demo_duration_s, include_subs=False)
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r2.returncode != 0:
        raise MuxError(f"Remux falló: {r.stderr[-800:]}")
