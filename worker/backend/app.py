"""Convertidor 3D — servidor local (FastAPI + frontend estático).

Arranque:  python -m backend.app   (desde la raíz del proyecto)
La app escucha SOLO en 127.0.0.1 (accede a disco y GPU locales).
"""
from __future__ import annotations

import asyncio
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api.routes import router
from backend.core.jobs import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    manager.attach_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION,
              lifespan=lifespan)
app.include_router(router)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True),
          name="frontend")


def main() -> None:
    import uvicorn
    url = f"http://{config.HOST}:{config.PORT}"
    # solo ASCII en consola: las terminales Windows cp1252 revientan con
    # caracteres multi-byte
    print(f"\n  {config.APP_NAME} v{config.APP_VERSION}  ->  {url}")
    if config.SIMULATE:
        print("  [!] MODO SIMULACION activo (CONVERTIDOR3D_SIMULATE=1): "
              "sin conversion real\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
