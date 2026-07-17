"""Detección del backend de cómputo: CUDA → DirectML (iGPU/dGPU DX12) → CPU.

Sin GPU NVIDIA, la profundidad corre con ONNX Runtime:
 - DmlExecutionProvider (cualquier GPU DX12: AMD/Intel integradas incluidas)
 - CPUExecutionProvider como último recurso
El warp del modo rápido usa PyTorch CPU. El modo Calidad (SVD) exige CUDA.
"""
from __future__ import annotations

import functools
import os
import platform
import subprocess
from dataclasses import dataclass, field, asdict

from backend.core.gpu import detect_gpus, GpuInfo


@dataclass
class ComputeInfo:
    kind: str                    # 'cuda' | 'dml' | 'cpu'
    name: str                    # nombre del dispositivo para la UI
    vram_gb: float               # VRAM (cuda) o RAM del sistema (dml/cpu)
    gpu: GpuInfo | None = None   # solo kind='cuda'
    cpu_name: str = ""
    cpu_threads: int = 0
    ram_gb: float = 0.0
    amf: bool = False            # encoder hevc_amf disponible (AMD)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gpu"] = self.gpu.to_dict() if self.gpu else None
        return d


def _dml_available() -> bool:
    try:
        import onnxruntime as ort
        return "DmlExecutionProvider" in ort.get_available_providers()
    except ImportError:
        return False


def _gpu_names_windows() -> list[str]:
    """Nombres de adaptadores gráficos (para etiquetar el dispositivo DML)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=15)
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except (subprocess.SubprocessError, OSError):
        return []


def _ram_gb() -> float:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            # dwLength, dwMemoryLoad, ullTotalPhys + 6 campos ull restantes
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong)] + [
                        (f"_p{i}", ctypes.c_ulonglong) for i in range(6)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return 0.0
        return round(st.ullTotalPhys / 2**30, 1)
    except Exception:
        return 0.0


def _cpu_name() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except OSError:
        return platform.processor() or "CPU"


@functools.lru_cache(maxsize=1)
def detect_compute() -> ComputeInfo:
    cpu_name = _cpu_name()
    threads = os.cpu_count() or 4
    ram = _ram_gb()

    gpus = detect_gpus()
    if gpus:
        from backend.core.estimator import match_gpu
        g = match_gpu(gpus[0])
        return ComputeInfo(kind="cuda", name=g.name, vram_gb=g.vram_gb, gpu=g,
                           cpu_name=cpu_name, cpu_threads=threads, ram_gb=ram)

    from backend.pipeline.encode import _ffmpeg_encoders
    amf = "hevc_amf" in _ffmpeg_encoders()

    if _dml_available():
        names = [n for n in _gpu_names_windows() if "NVIDIA" not in n.upper()]
        name = names[0] if names else "GPU DirectX 12"
        info = ComputeInfo(kind="dml", name=f"{name} (DirectML)", vram_gb=ram,
                           cpu_name=cpu_name, cpu_threads=threads, ram_gb=ram,
                           amf=amf)
        info.notes.append("Profundidad en la GPU integrada vía ONNX Runtime + "
                          "DirectML; warp en CPU. Mucho más lento que CUDA.")
        if ram and ram < 24:
            info.notes.append(f"RAM compartida limitada ({ram:.0f} GB): "
                              "recomendado procesar a 1080p.")
        return info

    info = ComputeInfo(kind="cpu", name=f"{cpu_name} ({threads} hilos)",
                       vram_gb=ram, cpu_name=cpu_name, cpu_threads=threads,
                       ram_gb=ram, amf=amf)
    info.notes.append("Sin GPU utilizable: todo en CPU (muy lento). "
                      "Instala onnxruntime-directml si tienes GPU DX12.")
    return info
