"""Registro de motores de IA (addons) descubiertos en worker/engines/.

Cada motor es una carpeta worker/engines/<id>/ con:
  manifest.json   identidad, etapa, requisitos, pesos, semillas del estimador
  engine.py       def create(cfg: dict, models_dir: Path) -> motor (engine_api)
  probe.py        def probe(models_dir: Path) -> {"available", "missing", ...}
  requirements.txt (opcional) dependencias pip propias del motor

Un addon de terceros = soltar una carpeta aqui; nada del core se toca.
Los modulos se cargan por ruta (importlib), sin exigir paquete Python.
La validacion del manifest es a mano contra el esquema normativo
worker/engines/manifest.schema.json (sin dependencia de jsonschema).
"""
from __future__ import annotations

import functools
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

ENGINES_DIR = Path(__file__).resolve().parent / "engines"
STAGES = ("depth", "stereo", "inpaint")
API_MAJOR = 1  # major de engine_api que este core sabe cargar


class EngineError(Exception):
    pass


@dataclass
class EngineSpec:
    id: str
    stage: str
    label: str
    api_version: str
    dir: Path
    requires_compute: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    compatible: bool = True
    errors: list[str] = field(default_factory=list)


def _validate_manifest(data: dict, folder: str) -> list[str]:
    """Validacion minima y con mensajes claros (esquema normativo:
    engines/manifest.schema.json)."""
    errs = []
    if not isinstance(data, dict):
        return [f"{folder}: el manifest no es un objeto JSON"]
    if data.get("manifest_version") != 1:
        errs.append(f"{folder}: manifest_version debe ser 1")
    if not isinstance(data.get("id"), str) or not data.get("id"):
        errs.append(f"{folder}: falta 'id' (string)")
    elif data["id"] != folder:
        errs.append(f"{folder}: 'id' ({data['id']}) debe coincidir con la carpeta")
    if data.get("stage") not in STAGES:
        errs.append(f"{folder}: 'stage' debe ser uno de {STAGES}")
    if not isinstance(data.get("label"), str) or not data.get("label"):
        errs.append(f"{folder}: falta 'label' (string)")
    if not isinstance(data.get("api_version"), str):
        errs.append(f"{folder}: falta 'api_version' (p.ej. \"1.x\")")
    rc = data.get("requires_compute", [])
    if not isinstance(rc, list) or any(not isinstance(x, str) for x in rc):
        errs.append(f"{folder}: 'requires_compute' debe ser lista de strings")
    for i, w in enumerate(data.get("weights", []) or []):
        if not isinstance(w, dict) or w.get("kind") not in ("hf", "hf-snapshot", "git"):
            errs.append(f"{folder}: weights[{i}].kind debe ser hf|hf-snapshot|git")
        elif not w.get("dest"):
            errs.append(f"{folder}: weights[{i}] necesita 'dest'")
    return errs


def _api_compatible(ver: str) -> bool:
    """Acepta '1.x', '1', '1.0'... del mismo major que el core."""
    major = ver.split(".", 1)[0]
    return major.isdigit() and int(major) == API_MAJOR


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EngineError(f"No se pudo cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=1)
def load_manifests() -> dict[str, EngineSpec]:
    """Escanea worker/engines/. Un manifest invalido NO tumba el resto: el
    motor queda listado como incompatible con sus errores."""
    specs: dict[str, EngineSpec] = {}
    if not ENGINES_DIR.exists():
        return specs
    for d in sorted(ENGINES_DIR.iterdir()):
        mpath = d / "manifest.json"
        if not d.is_dir() or not mpath.exists():
            continue
        try:
            data = json.loads(mpath.read_text("utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            specs[d.name] = EngineSpec(id=d.name, stage="?", label=d.name,
                                       api_version="?", dir=d, compatible=False,
                                       errors=[f"manifest.json ilegible: {e}"])
            continue
        errs = _validate_manifest(data, d.name)
        spec = EngineSpec(
            id=data.get("id", d.name), stage=data.get("stage", "?"),
            label=data.get("label", d.name),
            api_version=data.get("api_version", "?"), dir=d,
            requires_compute=list(data.get("requires_compute", [])),
            manifest=data, errors=errs,
            compatible=not errs and _api_compatible(data.get("api_version", "")),
        )
        if not spec.compatible and not errs:
            spec.errors.append(
                f"api_version {spec.api_version} incompatible con engine_api {API_MAJOR}.x")
        specs[spec.id] = spec
    return specs


def probe_engine(spec: EngineSpec, models_dir: Path) -> dict:
    """{"available": bool, "missing": [str], "detail": str|None}."""
    if not spec.compatible:
        return {"available": False, "missing": spec.errors, "detail": None}
    try:
        mod = _load_module(spec.dir / "probe.py", f"engine_probe_{spec.id}")
        out = mod.probe(models_dir)
        return {"available": bool(out.get("available")),
                "missing": list(out.get("missing", [])),
                "detail": out.get("detail")}
    except Exception as e:  # noqa: BLE001 — un probe roto no tumba el sondeo
        return {"available": False, "missing": [f"probe fallo: {e}"], "detail": None}


def create_engine(engine_id: str, cfg: dict, models_dir: Path):
    """Instancia el motor (import perezoso: solo al crear el job)."""
    spec = load_manifests().get(engine_id)
    if spec is None:
        raise EngineError(f"Motor desconocido: '{engine_id}' "
                          f"(disponibles: {sorted(load_manifests())})")
    if not spec.compatible:
        raise EngineError(f"Motor '{engine_id}' incompatible: {'; '.join(spec.errors)}")
    mod = _load_module(spec.dir / "engine.py", f"engine_{spec.id}")
    return mod.create(cfg, models_dir)
