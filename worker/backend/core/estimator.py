"""Estimación de tiempos de conversión según GPU y configuración.

Modelo de coste: el pipeline solapa decode → profundidad → warp/inpaint →
encode (productor-consumidor), así que el tiempo por frame es el de la etapa
más lenta dividido por un factor de eficiencia de solape (0.85).

Los valores base son de RTX 4090 (≈ A100 en estos modelos, ver investigación:
README de Video-Depth-Anything, paper DreamStereo tabla 1, NVENC App Note
SDK 13.0). El resto de GPUs escala por `scaler` (media geométrica de ratio
FP16-tensor y ancho de banda vs 4090). La calibración local (micro-benchmark)
sustituye estos valores estáticos cuando existe.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

from backend import config
from backend.core.gpu import GpuInfo

# ── BD de GPUs: escalador de rendimiento vs RTX 4090 ──────────────────────
GPU_DB: dict[str, float] = {
    "RTX 3060 Ti": 0.30, "RTX 3060": 0.24,
    "RTX 3070 Ti": 0.39, "RTX 3070": 0.37,
    "RTX 3080 Ti": 0.58, "RTX 3080": 0.52,
    "RTX 3090 Ti": 0.67, "RTX 3090": 0.63,
    "RTX 4060 Ti": 0.28, "RTX 4060": 0.22,
    "RTX 4070 Ti SUPER": 0.56, "RTX 4070 Ti": 0.52,
    "RTX 4070 SUPER": 0.48, "RTX 4070": 0.42,
    "RTX 4080 SUPER": 0.67, "RTX 4080": 0.65,
    "RTX 4090": 1.00,
    "RTX 5060 Ti": 0.32, "RTX 5060": 0.26,
    "RTX 5070 Ti": 0.62, "RTX 5070": 0.50,
    "RTX 5080": 0.81, "RTX 5090": 1.50,
}
LAPTOP_FACTOR = 0.70
UNKNOWN_SCALER = 0.30  # conservador para GPUs no catalogadas

# ── Rendimiento base en RTX 4090 (fps por etapa) ───────────────────────────
DEPTH_FPS = {"vda_s": 130.0, "vda_b": 95.0, "vda_l": 70.0}   # 518px fp16, ventana 32
DEPTH_4K_FACTOR = 0.90        # sobrecoste de E/S preparando frames 4K
WARP_FPS = {"1080p": 110.0, "4k": 28.0}
HQ_INPAINT_FPS_8STEPS = {"1080p": 0.85, "4k": 0.22}          # difusión SVD, 8 pasos
ENCODE_FPS = {"hsbs_1080": 300.0, "fsbs_1080": 150.0, "hsbs_4k": 75.0, "fsbs_4k": 37.0}
DECODE_FPS = 350.0            # NVDEC HEVC 4K — nunca cuello de botella
OVERLAP_EFFICIENCY = 0.85
SETUP_SECONDS = 120.0         # carga de modelos + detección de escenas

# ── Rendimiento base SIN CUDA (fps absolutos, clase Ryzen 5700U + Vega 8) ──
# Profundidad = Depth Anything V2 por frame vía ONNX Runtime. Provisionales
# hasta calibración local (benchmark ViT-proxy medido en un 5700U:
# DML 11.1 it/s vs CPU 6.7 it/s → modelo real ≈ 1/3 de eso).
FALLBACK_DEPTH_FPS = {
    "dml": {"vda_s": 3.5, "vda_b": 1.2, "vda_l": 0.35},
    "cpu": {"vda_s": 2.0, "vda_b": 0.7, "vda_l": 0.20},
}
FALLBACK_WARP_FPS = {"1080p": 3.0, "4k": 0.8}       # PyTorch CPU
FALLBACK_ENCODE_FPS = {                              # AMF 8-bit / x265 CPU
    "amf": {"hsbs_1080": 120.0, "fsbs_1080": 60.0, "hsbs_4k": 30.0, "fsbs_4k": 15.0},
    "x265": {"hsbs_1080": 12.0, "fsbs_1080": 6.0, "hsbs_4k": 3.0, "fsbs_4k": 1.5},
}
FALLBACK_CPU_SCALE_REF_THREADS = 16   # los valores de arriba son para 16 hilos

# Escaladores de NVENC/NVDEC por generación son ~1 (no van con tensor cores);
# se aplican solo a etapas de IA.

DEPTH_MODELS = {
    "vda_s": {"label": "Small (28M)", "license": "Apache-2.0", "comercial": True},
    "vda_b": {"label": "Base (113M)", "license": "CC-BY-NC-4.0", "comercial": False},
    "vda_l": {"label": "Large (382M)", "license": "CC-BY-NC-4.0", "comercial": False},
}
OUTPUTS = {
    "hsbs_1080": {"label": "Half-SBS 1080p", "res": "1920×1080", "tv3d": True},
    "hsbs_4k": {"label": "Half-SBS 4K", "res": "3840×2160", "tv3d": True, "recomendado": True},
    "fsbs_1080": {"label": "Full-SBS 1080p", "res": "3840×1080", "tv3d": True},
    "fsbs_4k": {"label": "Full-SBS 4K", "res": "7680×2160", "tv3d": False},
}


@dataclass
class Estimate:
    proc_res: str          # '1080p' | '4k'
    depth_model: str       # 'vda_s' | 'vda_b' | 'vda_l'
    mode: str              # 'fast' | 'hq'
    inpaint_steps: int     # solo hq
    output: str            # clave de OUTPUTS
    demo_seconds: float
    full_seconds: float
    vram_needed_gb: float
    status: str            # 'ok' | 'warn' | 'no'
    notes: list[str]
    calibrated: bool

    def to_dict(self) -> dict:
        return asdict(self)


def match_gpu(gpu: GpuInfo) -> GpuInfo:
    """Anota la GPU con su escalador de la BD (o heurística si es desconocida)."""
    name = gpu.name
    best_key = None
    for key in sorted(GPU_DB, key=len, reverse=True):
        if re.search(re.escape(key), name, re.IGNORECASE):
            best_key = key
            break
    if best_key:
        gpu.scaler = GPU_DB[best_key]
        gpu.known = True
        if re.search(r"laptop|mobile|max-q", name, re.IGNORECASE):
            gpu.scaler = round(gpu.scaler * LAPTOP_FACTOR, 3)
            gpu.notes.append("Variante portátil: rendimiento estimado ×0.7")
    else:
        gpu.scaler = UNKNOWN_SCALER
        gpu.known = False
        gpu.notes.append(
            "GPU no catalogada: estimación conservadora; la calibración la ajustará")
    return gpu


def load_calibration() -> dict[str, float]:
    """fps medidos por etapa en ESTA máquina: {'depth:vda_s:1080p': fps, ...}"""
    if config.CALIBRATION_FILE.exists():
        try:
            return json.loads(config.CALIBRATION_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_calibration(measurements: dict[str, float]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = load_calibration()
    current.update(measurements)
    config.CALIBRATION_FILE.write_text(json.dumps(current, indent=2), "utf-8")


def _stage_fps(key: str, base_4090: float, scaler: float, cal: dict[str, float],
               ai_stage: bool = True) -> tuple[float, bool]:
    """fps de una etapa: calibración local si existe, si no base×escalador."""
    if key in cal:
        return cal[key], True
    return (base_4090 * scaler if ai_stage else base_4090), False


def _vram_check(proc_res: str, depth_model: str, mode: str, vram: float) -> tuple[float, str, list[str]]:
    """(vram_necesaria, status, notas) para la combinación."""
    notes: list[str] = []
    # Profundidad (ventana 32 frames fp16; reducible a 16 con leve coste en costuras)
    depth_need = {"vda_s": 7.0, "vda_b": 12.0, "vda_l": 24.0}[depth_model]
    depth_min = {"vda_s": 4.0, "vda_b": 8.0, "vda_l": 13.0}[depth_model]
    status = "ok"
    if vram < depth_need:
        if vram >= depth_min:
            status = "warn"
            notes.append("VRAM justa para el modelo de profundidad: ventana reducida (16 frames)")
        else:
            return depth_need, "no", ["VRAM insuficiente para el modelo de profundidad"]
    need = depth_need
    if mode == "hq":
        hq_need = 16.0 if proc_res == "1080p" else 24.0
        hq_min = 12.0 if proc_res == "1080p" else 16.0
        need = max(need, hq_need)
        if vram < hq_need:
            if vram >= hq_min:
                status = "warn"
                notes.append("Inpainting con downscale + tiling + chunks cortos (más lento)")
            else:
                return need, "no", ["VRAM insuficiente para el inpainting de difusión "
                                    f"(mínimo {hq_min:.0f} GB en {proc_res})"]
    return need, status, notes


def _estimate_fallback(duration_s: float, fps: float, compute,
                       proc_res: str, depth_model: str, mode: str,
                       output: str, demo_duration_s: float,
                       cal: dict[str, float], notes: list[str]) -> Estimate:
    """Estimación para backends sin CUDA (dml = iGPU DirectML, cpu)."""
    kind = compute.kind  # 'dml' | 'cpu'
    threads = compute.cpu_threads or 8
    cpu_scale = min(threads / FALLBACK_CPU_SCALE_REF_THREADS, 1.5)

    calibrated = False
    if mode == "hq":
        return Estimate(proc_res=proc_res, depth_model=depth_model, mode=mode,
                        inpaint_steps=0, output=output, demo_seconds=0,
                        full_seconds=0, vram_needed_gb=16,
                        status="no",
                        notes=["El modo Calidad (inpainting SVD) requiere GPU "
                               "NVIDIA con CUDA"], calibrated=False)

    depth_key = f"{kind}:depth:{depth_model}"
    depth_fps = cal.get(depth_key)
    if depth_fps is None:
        depth_fps = FALLBACK_DEPTH_FPS[kind][depth_model]
        if kind == "cpu":
            depth_fps *= cpu_scale
    else:
        calibrated = True

    warp_key = f"{kind}:warp:{proc_res}"
    warp_fps = cal.get(warp_key)
    if warp_fps is None:
        warp_fps = FALLBACK_WARP_FPS[proc_res] * cpu_scale
    else:
        calibrated = True

    enc_kind = "amf" if getattr(compute, "amf", False) else "x265"
    encode_fps = cal.get(f"{kind}:encode:{output}",
                         FALLBACK_ENCODE_FPS[enc_kind][output] *
                         (cpu_scale if enc_kind == "x265" else 1.0))

    # El runner solapa profundidad (iGPU/DML) y warp (CPU) por lotes, así que
    # manda la etapa dominante (+10% de coste de coordinación/decode); el
    # encode corre aparte en su proceso ffmpeg.
    t_frame = max(1 / depth_fps * 1.10, 1 / warp_fps * 1.10, 1 / encode_fps)
    total_frames = duration_s * fps
    demo_frames = min(demo_duration_s, duration_s) * fps
    full_seconds = SETUP_SECONDS + total_frames * t_frame
    demo_seconds = SETUP_SECONDS * 0.5 + demo_frames * t_frame

    status = "warn"
    label = "iGPU DirectML" if kind == "dml" else "CPU"
    notes.insert(0, f"Sin CUDA: profundidad por frame (Depth Anything V2 ONNX, "
                    f"{label}) + suavizado temporal — mucho más lento")
    if proc_res == "4k":
        status = "warn"
        notes.append("4K en este equipo es MUY lento; recomendado 1080p")
        if compute.ram_gb and compute.ram_gb < 24:
            notes.append(f"RAM ({compute.ram_gb:.0f} GB) justa para 4K")
    if depth_model != "vda_s":
        notes.append("Base/Large por frame en este backend: horas extra y "
                     "licencia CC-BY-NC")

    return Estimate(proc_res=proc_res, depth_model=depth_model, mode=mode,
                    inpaint_steps=0, output=output,
                    demo_seconds=round(demo_seconds),
                    full_seconds=round(full_seconds),
                    vram_needed_gb=0.0, status=status, notes=notes,
                    calibrated=calibrated)


def estimate_one(duration_s: float, fps: float, gpu: GpuInfo | None,
                 proc_res: str, depth_model: str, mode: str,
                 inpaint_steps: int, output: str,
                 demo_duration_s: float = 60.0, compute=None) -> Estimate:
    cal = load_calibration()

    notes: list[str] = []
    # Coherencia salida/proceso
    if output == "fsbs_4k" and proc_res != "4k":
        notes.append("Full-SBS 4K requiere procesar a 4K")
    if output == "hsbs_4k" and proc_res == "1080p":
        notes.append("Salida 4K desde proceso 1080p: se reescala (calidad limitada)")
    if output == "fsbs_4k":
        notes.append("⚠ 7680×2160 excede el decodificador de muchas TV 3D (uso PC/VR)")

    # Backend sin CUDA → estimación específica (DirectML/CPU)
    if gpu is None and compute is not None and compute.kind in ("dml", "cpu"):
        return _estimate_fallback(duration_s, fps, compute, proc_res,
                                  depth_model, mode, output, demo_duration_s,
                                  cal, notes)

    scaler = gpu.scaler if gpu and gpu.scaler else UNKNOWN_SCALER
    vram = gpu.vram_gb if gpu else 0.0

    calibrated = False
    depth_key = f"depth:{depth_model}:{proc_res}"
    depth_base = DEPTH_FPS[depth_model] * (DEPTH_4K_FACTOR if proc_res == "4k" else 1.0)
    depth_fps, c1 = _stage_fps(depth_key, depth_base, scaler, cal)
    calibrated |= c1

    if mode == "fast":
        warp_fps, c2 = _stage_fps(f"warp:{proc_res}", WARP_FPS[proc_res], scaler, cal)
        stereo_fps = warp_fps
    else:
        base8 = HQ_INPAINT_FPS_8STEPS[proc_res]
        # el coste crece con los pasos, con parte fija (VAE/CLIP): t ∝ 0.35 + 0.65·pasos/8
        step_factor = 0.35 + 0.65 * (inpaint_steps / 8.0)
        stereo_fps, c2 = _stage_fps(f"inpaint:{proc_res}:{inpaint_steps}",
                                    base8 / step_factor, scaler, cal)
    calibrated |= c2

    encode_fps, _ = _stage_fps(f"encode:{output}", ENCODE_FPS[output], 1.0, cal, ai_stage=False)

    t_frame = max(1 / depth_fps, 1 / stereo_fps, 1 / encode_fps, 1 / DECODE_FPS)
    t_frame /= OVERLAP_EFFICIENCY

    total_frames = duration_s * fps
    demo_frames = min(demo_duration_s, duration_s) * fps
    full_seconds = SETUP_SECONDS + total_frames * t_frame
    demo_seconds = SETUP_SECONDS * 0.5 + demo_frames * t_frame

    vram_needed, status, vram_notes = _vram_check(proc_res, depth_model, mode, vram)
    notes.extend(vram_notes)
    if gpu is None:
        status = "no"
        notes.append("Sin GPU NVIDIA detectada")
    elif status == "warn":
        # penalización por ajustes de VRAM (offload, chunks cortos, tiling)
        factor = 1.3 if mode == "fast" else 2.0
        full_seconds *= factor
        demo_seconds *= factor

    return Estimate(
        proc_res=proc_res, depth_model=depth_model, mode=mode,
        inpaint_steps=inpaint_steps if mode == "hq" else 0, output=output,
        demo_seconds=round(demo_seconds), full_seconds=round(full_seconds),
        vram_needed_gb=vram_needed, status=status, notes=notes,
        calibrated=calibrated,
    )


def estimate_matrix(duration_s: float, fps: float, gpu: GpuInfo | None,
                    inpaint_steps: int = 8, demo_duration_s: float = 60.0,
                    compute=None) -> list[dict]:
    """Todas las combinaciones (proceso × modelo × modo × salida) para la tabla."""
    rows = []
    for proc_res in ("1080p", "4k"):
        for depth_model in DEPTH_MODELS:
            for mode in ("fast", "hq"):
                for output in OUTPUTS:
                    if output == "fsbs_4k" and proc_res != "4k":
                        continue  # combinación incoherente: no se muestra
                    rows.append(estimate_one(
                        duration_s, fps, gpu, proc_res, depth_model, mode,
                        inpaint_steps, output, demo_duration_s,
                        compute=compute).to_dict())
    return rows
