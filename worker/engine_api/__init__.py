"""Contrato publico entre el pipeline y los motores de IA (addons).

Los motores (worker/engines/<id>/) dependen SOLO de este paquete, nunca de
backend/ directamente. Versionado semver: cambios aditivos = minor; cambios
que rompen la firma = nuevo modulo v2 conviviendo con v1.
"""
from engine_api.v1 import (  # noqa: F401
    API_VERSION,
    ChunkCtx,
    DepthEngine,
    InpaintEngine,
    StereoEngine,
    TemporalStabilizer,
)
