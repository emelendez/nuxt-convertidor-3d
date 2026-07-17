"""Detección de GPU NVIDIA (pynvml con fallback a nvidia-smi)."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict


@dataclass
class GpuInfo:
    name: str
    vram_gb: float
    driver: str | None = None
    index: int = 0
    # Rellenado por el estimador a partir de la BD de rendimiento:
    scaler: float | None = None       # rendimiento relativo a RTX 4090
    known: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_pynvml() -> list[GpuInfo] | None:
    try:
        import pynvml
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
    except Exception:
        return None
    try:
        driver = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode()
        gpus = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpus.append(GpuInfo(name=name, vram_gb=round(mem.total / 2**30, 1),
                                driver=driver, index=i))
        return gpus
    except Exception:
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _detect_nvidia_smi() -> list[GpuInfo] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        m = re.match(r"([\d.]+)", parts[2])
        vram_mb = float(m.group(1)) if m else 0.0
        gpus.append(GpuInfo(index=int(parts[0]), name=parts[1],
                            vram_gb=round(vram_mb / 1024, 1), driver=parts[3]))
    return gpus or None


def detect_gpus() -> list[GpuInfo]:
    """Devuelve las GPUs NVIDIA detectadas (lista vacía si no hay)."""
    return _detect_pynvml() or _detect_nvidia_smi() or []
