"""Configuración global del Convertidor 3D."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "Convertidor 3D"
APP_VERSION = "0.1.0"

ROOT_DIR = Path(__file__).resolve().parent.parent   # = worker/
# Raiz del PROYECTO (worker/..): models/, data/ y tools/ viven ahi en este
# repo (fork 2026-07-18; en el proyecto original backend/ colgaba de la raiz).
# Node siempre inyecta CONVERTIDOR3D_MODELS/DATA al spawnear el worker; estos
# defaults solo importan al ejecutar detect.py/cli.py A MANO, y antes
# apuntaban a worker/models y worker/tools (inexistentes -> sondeo enganoso).
PROJECT_ROOT = ROOT_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
# Modelos y datos pueden vivir en otro disco (p. ej. D:) si C: anda justo:
#   setx CONVERTIDOR3D_MODELS "D:\convertidor-3d\models"
#   setx CONVERTIDOR3D_DATA   "D:\convertidor-3d\data"
MODELS_DIR = Path(os.environ.get("CONVERTIDOR3D_MODELS", PROJECT_ROOT / "models"))
DATA_DIR = Path(os.environ.get("CONVERTIDOR3D_DATA", PROJECT_ROOT / "data"))
JOBS_DIR = DATA_DIR / "jobs"
CALIBRATION_FILE = DATA_DIR / "calibration.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_OUTPUT_DIR = Path.home() / "Videos" / "Convertidor3D"

# FFmpeg embebido (tools/ffmpeg/bin): viaja con la carpeta al copiarla.
# Se antepone al PATH del proceso para que shutil.which() lo encuentre.
_FFMPEG_BIN = PROJECT_ROOT / "tools" / "ffmpeg" / "bin"
if _FFMPEG_BIN.is_dir():
    os.environ["PATH"] = str(_FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", "")

# Modo simulación: pipeline falso con tiempos del estimador, para desarrollo
# de UI en máquinas sin GPU/FFmpeg. Nunca se activa solo.
SIMULATE = os.environ.get("CONVERTIDOR3D_SIMULATE", "0") == "1"

HOST = "127.0.0.1"  # solo local: la app accede a disco y GPU de esta máquina
PORT = int(os.environ.get("CONVERTIDOR3D_PORT", "8765"))

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".ts", ".m2ts", ".webm"}


def _default_settings() -> dict:
    return {
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "language": "es",
        "theme": "auto",
    }


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return {**_default_settings(), **json.loads(SETTINGS_FILE.read_text("utf-8"))}
        except (json.JSONDecodeError, OSError):
            pass
    return _default_settings()


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), "utf-8")


def ensure_dirs() -> None:
    for d in (DATA_DIR, JOBS_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
