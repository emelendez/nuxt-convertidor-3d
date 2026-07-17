"""Rutas de la API (FastAPI). Todo escucha solo en 127.0.0.1."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend import config
from backend.core import estimator
from backend.core.compute import detect_compute
from backend.core.gpu import detect_gpus
from backend.core.jobs import manager
from backend.pipeline import probe as probe_mod
from backend.pipeline import decode as decode_mod
from backend.pipeline import depth as depth_mod
from backend.pipeline import stereo_fast, stereo_hq
from backend.pipeline import encode as encode_mod

router = APIRouter(prefix="/api")


def _gpus():
    """GPUs reales; en modo simulación sin GPU, una ficticia etiquetada."""
    gpus = detect_gpus()
    if not gpus and config.SIMULATE:
        from backend.core.gpu import GpuInfo
        gpus = [GpuInfo(name="NVIDIA GeForce RTX 4070 (simulada)", vram_gb=12.0,
                        driver="—")]
    return [estimator.match_gpu(g) for g in gpus]


# ── salud y capacidades ─────────────────────────────────────────────────────
@router.get("/health")
def health() -> dict:
    gpus = [g.to_dict() for g in _gpus()]
    compute = detect_compute()
    depth_kind, depth_missing = depth_mod.depth_backend("vda_s")
    return {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "simulate": config.SIMULATE,
        "compute": compute.to_dict(),
        "components": {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": probe_mod.ffprobe_available(),
            "nvenc": encode_mod.nvenc_available(),
            "encoder": encode_mod.pick_encoder() if shutil.which("ffmpeg") else None,
            "gpu": bool(gpus),
            "depth": depth_kind,          # 'vda' | 'onnx' | None
            "depth_vda_s": not depth_mod.check_available("vda_s"),
            "stereo_fast": not stereo_fast.check_available(),
            "stereo_hq": not stereo_hq.check_available() and compute.kind == "cuda",
        },
        "missing": {
            "depth": depth_missing,
            "stereo_hq": stereo_hq.check_available(),
        },
        "gpus": gpus,
        "settings": config.load_settings(),
    }


@router.get("/gpu")
def gpu() -> dict:
    return {"gpus": [g.to_dict() for g in _gpus()]}


# ── selección de fichero ────────────────────────────────────────────────────
def _is_local(request: Request) -> bool:
    return request.client is None or request.client.host in ("127.0.0.1", "::1")


@router.post("/browse")
def browse(request: Request) -> dict:
    """Diálogo nativo de Windows para elegir el MKV (solo peticiones locales)."""
    if not _is_local(request):
        raise HTTPException(403, "Solo disponible en local")
    # tkinter debe correr en un proceso propio: no es thread-safe con uvicorn
    code = (
        "import tkinter as tk, tkinter.filedialog as fd\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = fd.askopenfilename(title='Elige la película', filetypes="
        "[('Vídeo', '*.mkv *.mp4 *.m4v *.mov *.ts *.m2ts'), ('Todos', '*.*')])\n"
        "print(p or '')"
    )
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=300)
        path = out.stdout.strip()
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Diálogo cancelado por tiempo")
    return {"path": path or None}


class ProbeBody(BaseModel):
    path: str


@router.post("/probe")
def probe(body: ProbeBody) -> dict:
    try:
        return probe_mod.probe(body.path)
    except probe_mod.ProbeError as e:
        raise HTTPException(400, str(e)) from e


# ── estimaciones ────────────────────────────────────────────────────────────
class EstimateBody(BaseModel):
    duration_s: float = Field(gt=0)
    fps: float = Field(gt=0, default=24.0)
    inpaint_steps: int = 8
    demo_duration_s: float = 60.0
    gpu_index: int = 0


@router.post("/estimate")
def estimate(body: EstimateBody) -> dict:
    gpus = _gpus()
    gpu_sel = gpus[body.gpu_index] if body.gpu_index < len(gpus) else (gpus[0] if gpus else None)
    compute = detect_compute()
    rows = estimator.estimate_matrix(body.duration_s, body.fps, gpu_sel,
                                     body.inpaint_steps, body.demo_duration_s,
                                     compute=compute)
    return {
        "gpu": gpu_sel.to_dict() if gpu_sel else None,
        "compute": compute.to_dict(),
        "rows": rows,
        "outputs": estimator.OUTPUTS,
        "depth_models": estimator.DEPTH_MODELS,
        "calibration": estimator.load_calibration(),
    }


# ── miniaturas para el selector de inicio de demo ──────────────────────────
class ThumbsBody(BaseModel):
    path: str
    timestamps: list[float]


@router.post("/thumbnails")
def thumbnails(body: ThumbsBody) -> dict:
    if len(body.timestamps) > 12:
        raise HTTPException(400, "Máximo 12 miniaturas por petición")
    try:
        thumbs = decode_mod.extract_thumbnails(body.path, body.timestamps)
    except decode_mod.DecodeError as e:
        raise HTTPException(400, str(e)) from e
    return {"thumbnails": [base64.b64encode(t).decode() if t else None
                           for t in thumbs]}


# ── trabajos ────────────────────────────────────────────────────────────────
class JobBody(BaseModel):
    kind: str = Field(pattern="^(demo|full)$")
    path: str
    cfg: dict
    demo_start_mode: str = "fixed"      # fixed | middle | custom
    demo_start_s: float = 600.0
    demo_duration_s: float = 60.0


@router.post("/jobs")
def create_job(body: JobBody) -> dict:
    try:
        info = probe_mod.probe(body.path)
    except probe_mod.ProbeError as e:
        if config.SIMULATE:
            # en simulación se acepta cualquier ruta con metadatos ficticios
            info = {"path": body.path, "filename": Path(body.path).name,
                    "duration_s": 7200.0, "video": {"fps": 24.0, "hdr": False},
                    "audio_tracks": [], "subtitle_tracks": [], "chapters": 0}
        else:
            raise HTTPException(400, str(e)) from e

    duration = info["duration_s"]
    required = {"proc_res", "depth_model", "mode", "output"}
    if not required.issubset(body.cfg):
        raise HTTPException(400, f"Config incompleta; faltan {required - set(body.cfg)}")
    cfg = {"divergence": 2.0, "convergence": 0.5, "inpaint_steps": 8,
           "tonemap": True, **body.cfg}

    if (cfg["mode"] == "hq" and detect_compute().kind != "cuda"
            and not config.SIMULATE):
        raise HTTPException(400, "El modo Calidad (inpainting SVD) requiere GPU "
                                 "NVIDIA con CUDA; usa el modo Rápido")

    if body.kind == "demo":
        dur = min(max(body.demo_duration_s, 10.0), 300.0)
        if body.demo_start_mode == "middle":
            start = max(duration / 2 - dur / 2, 0.0)
        elif body.demo_start_mode == "custom":
            start = min(max(body.demo_start_s, 0.0), max(duration - dur, 0.0))
        else:  # fixed: minuto 10 (o proporcional en vídeos cortos)
            start = min(600.0, duration * 0.25)
        segment = (start, min(dur, duration - start))
    else:
        segment = (0.0, duration)

    job = manager.submit(body.kind, info["path"], cfg, info, segment[0],
                         segment[1], simulate=config.SIMULATE)
    return {"job": job.public()}


@router.get("/jobs")
def list_jobs() -> dict:
    return {"jobs": [j.public() for j in
                     sorted(manager.jobs.values(), key=lambda j: j.created_at)]}


@router.get("/output-files")
def output_files(limit: int = 100) -> dict:
    """Lista de ficheros MKV en la carpeta de salida, ordenados por fecha descendente.
    Detecta automáticamente si son demos (contienen 'demo' en nombre/path)."""
    settings = config.load_settings()
    outdir = Path(settings.get("output_dir", config.DEFAULT_OUTPUT_DIR))
    
    if not outdir.exists():
        return {"files": []}
    
    files = []
    for fpath in outdir.rglob("*.mkv"):
        if not fpath.is_file():
            continue
        stat = fpath.stat()
        # Detectar si es demo: contiene "demo" en el nombre o path
        is_demo = "demo" in fpath.name.lower()
        files.append({
            "name": fpath.name,
            "path": str(fpath),
            "size_bytes": stat.st_size,
            "created_at": stat.st_mtime,  # timestamp unix
            "is_demo": is_demo,
        })
    
    # Ordenar por fecha descendente (más recientes primero)
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return {"files": files[:limit]}


# ── acciones sobre ficheros de salida (solo local) ──────────────────────────
class FileActionBody(BaseModel):
    path: str


def _output_dir() -> Path:
    settings = config.load_settings()
    return Path(settings.get("output_dir", config.DEFAULT_OUTPUT_DIR))


def _within_output_dir(p: Path) -> bool:
    """True si `p` está dentro de la carpeta de salida configurada. Evita que la
    API local abra o borre ficheros arbitrarios del disco (defensa en profundidad)."""
    try:
        p.resolve().relative_to(_output_dir().resolve())
        return True
    except (ValueError, OSError):
        return False


def _open(p: Path) -> None:
    """Abre `p` con la aplicación por defecto del sistema (multiplataforma)."""
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _preview_dir() -> Path:
    return config.DATA_DIR / "previews"


def _preview_cache_name(src: Path) -> str:
    """Nombre de caché determinista por (ruta, mtime, tamaño): si el fichero
    cambia, se regenera; si no, se reutiliza."""
    st = src.stat()
    key = f"{src}|{st.st_mtime_ns}|{st.st_size}|v1"
    return hashlib.sha1(key.encode()).hexdigest()[:16] + ".mp4"


@router.post("/output-files/preview")
def make_output_file_preview(body: FileActionBody, request: Request) -> dict:
    """Genera (o reutiliza de caché) un clip corto H.264 para previsualizar en el
    navegador un fichero de salida (HEVC/SBS). Devuelve el nombre para servirlo."""
    if not _is_local(request):
        raise HTTPException(403, "Solo disponible en local")
    p = Path(body.path)
    if not _within_output_dir(p):
        raise HTTPException(400, "Fuera de la carpeta de salida")
    if not p.exists():
        raise HTTPException(404, "Fichero no encontrado")
    if not shutil.which("ffmpeg"):
        raise HTTPException(400, "FFmpeg no está disponible para la previsualización")
    name = _preview_cache_name(p)
    out = _preview_dir() / name
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            encode_mod.make_output_preview(p, out)
        except encode_mod.EncodeError as e:
            raise HTTPException(500, str(e)) from e
    return {"name": name}


@router.get("/output-files/preview/{name}")
def serve_output_file_preview(name: str, request: Request):
    """Sirve un clip de previsualización ya generado (solo nombres de caché)."""
    if not _is_local(request):
        raise HTTPException(403, "Solo disponible en local")
    if not re.fullmatch(r"[0-9a-f]{8,40}\.mp4", name):
        raise HTTPException(400, "Nombre inválido")
    p = _preview_dir() / name
    if not p.exists():
        raise HTTPException(404, "Previsualización no disponible")
    return FileResponse(p, media_type="video/mp4")


@router.post("/open-output-dir")
def open_output_dir(request: Request) -> dict:
    """Abre la carpeta de salida configurada (la crea si no existe)."""
    if not _is_local(request):
        raise HTTPException(403, "Solo disponible en local")
    outdir = _output_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    _open(outdir)
    return {"ok": True, "path": str(outdir)}


@router.post("/output-files/delete")
def delete_output_file(body: FileActionBody, request: Request) -> dict:
    """Borra un fichero, solo si está dentro de la carpeta de salida."""
    if not _is_local(request):
        raise HTTPException(403, "Solo disponible en local")
    p = Path(body.path)
    if not _within_output_dir(p):
        raise HTTPException(400, "Solo se pueden borrar ficheros de la carpeta de salida")
    if not p.exists():
        raise HTTPException(404, "Fichero no encontrado")
    try:
        p.unlink()
    except OSError as e:
        raise HTTPException(500, f"No se pudo borrar: {e}") from e
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    if not manager.cancel(job_id):
        raise HTTPException(404, "Trabajo no encontrado")
    return {"ok": True}


@router.get("/jobs/{job_id}/preview")
def job_preview(job_id: str, codec: str = "h264"):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    name = "preview.mp4" if codec == "hevc" else "preview_h264.mp4"
    p = manager.workdir(job) / name
    if not p.exists():
        raise HTTPException(404, "Preview no disponible")
    return FileResponse(p, media_type="video/mp4")


# ── eventos SSE ─────────────────────────────────────────────────────────────
@router.get("/events")
async def events(request: Request):
    q = manager.subscribe()

    async def stream():
        try:
            # estado actual al conectar (cubre reconexiones)
            for j in manager.jobs.values():
                yield f"event: job\ndata: {_json(j.public())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: job\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


# ── ajustes ─────────────────────────────────────────────────────────────────
class SettingsBody(BaseModel):
    output_dir: str | None = None
    theme: str | None = None
    language: str | None = None


@router.post("/settings")
def update_settings(body: SettingsBody) -> dict:
    settings = config.load_settings()
    for k, v in body.model_dump(exclude_none=True).items():
        settings[k] = v
    config.save_settings(settings)
    return {"settings": settings}
