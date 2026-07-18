"""Descarga los pesos de UN motor segun su manifest.json (lo llama setup.ps1).

Uso:  python engine_install.py <ruta_manifest.json> <models_dir>

- Comprueba lo GATED antes de descargar nada: si algun peso tiene gated=true
  y no hay token de HuggingFace (env HF_TOKEN o login de huggingface-cli),
  sale con codigo 2 y un mensaje accionable, sin tocar la red.
- kind=hf: descarga ficheros concretos (con renombrado opcional).
- kind=hf-snapshot: snapshot completo del repo a models/<dest>.
- kind=git: NO se gestiona aqui (lo clona setup.ps1 con commit pineado).
- Idempotente: lo ya presente se salta. Reintenta 1 vez cada descarga.

Codigos de salida: 0 = ok, 2 = falta token HF (gated), 1 = error.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def _has_hf_token() -> bool:
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
        return bool(get_token())
    except Exception:
        return False


def _retry(fn, desc: str):
    for attempt in (1, 2):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            print(f"  reintento tras fallo en {desc}: {type(e).__name__}: {e}")
            time.sleep(3)


def main() -> int:
    manifest_path, models_dir = Path(sys.argv[1]), Path(sys.argv[2])
    m = json.loads(manifest_path.read_text("utf-8"))
    weights = [w for w in (m.get("weights") or []) if w.get("kind") != "git"]
    if not weights:
        print("  sin pesos que descargar")
        return 0

    if any(w.get("gated") for w in weights) and not _has_hf_token():
        gated = [w["repo"] for w in weights if w.get("gated")]
        print("FALTA TOKEN DE HUGGINGFACE para pesos gated: " + ", ".join(gated))
        print("  1) Acepta la licencia del modelo en huggingface.co/" + gated[0])
        print("  2) pip install -U \"huggingface_hub[cli]\" && huggingface-cli login")
        print("     (o define la variable de entorno HF_TOKEN)")
        return 2

    from huggingface_hub import hf_hub_download, snapshot_download

    for w in weights:
        dest = models_dir / w["dest"]
        dest.mkdir(parents=True, exist_ok=True)
        if w["kind"] == "hf":
            rename = w.get("rename") or {}
            for f in w.get("files", []):
                final = dest / rename.get(f, Path(f).name)
                if final.exists():
                    print(f"  ya presente: {final.name}")
                    continue
                p = _retry(lambda: hf_hub_download(repo_id=w["repo"], filename=f),
                           f"{w['repo']}/{f}")
                shutil.copy(p, final)
                print(f"  OK {final.name}")
        elif w["kind"] == "hf-snapshot":
            if dest.exists() and any(dest.iterdir()):
                print(f"  snapshot ya presente: {w['dest']}")
                continue
            _retry(lambda: snapshot_download(w["repo"], local_dir=str(dest)),
                   f"snapshot {w['repo']}")
            print(f"  OK snapshot {w['dest']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
