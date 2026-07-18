# ADR: Arquitectura de motores addon para el pipeline 2D→3D

- **Fecha:** 2026-07-18
- **Estado:** aceptado e implementado (fases 0-4)
- **Issue:** [#4](https://github.com/emelendez/nuxt-convertidor-3d/issues/4)

## Contexto

El modo Calidad dependía de StereoCrafter + Stable Video Diffusion XT 1.1, un
modelo **gated** en HuggingFace (licencia + login obligatorios) y CUDA-only.
Se quería poder prescindir de esa dependencia y, en general, que los motores
de IA (profundidad / estéreo / relleno) fueran intercambiables por
configuración, incorporables según aparezcan modelos nuevos.

## Decisión

1. **Fork deliberado de `worker/backend/`.** Deja de ser copia verbatim del
   proyecto hermano (`D:\WEBAPPS\convertidor-3d`, solo-lectura y congelado).
   El coste de perder el diff fácil es bajo; la ganancia es poder integrar la
   identidad de motor en el manifest de reanudación y promover el warp a API
   pública sin monkeypatches frágiles.
2. **Formalizar las costuras existentes, no crear capas paralelas.** El
   pipeline ya tenía 8 seams (factoría de profundidad, estrategia estéreo por
   firma común, cascadas encoder/hwaccel/providers, detección central). La
   arquitectura los consolida en:
   - `worker/engine_api/` — contrato v1 (semver): `ChunkCtx`, protocolos
     `DepthEngine`/`StereoEngine`/`InpaintEngine`, y `ops.DibrWarper` (el warp
     DIBR con máscara de huecos como operación pública).
   - `worker/engines/<id>/` — un motor = una carpeta con `manifest.json` +
     `engine.py` + `probe.py` (+ `requirements.txt`). Descubrimiento por
     `worker/engine_registry.py` (importlib por ruta; un manifest inválido no
     tumba el resto). Esquema normativo: `worker/engines/manifest.schema.json`.
3. **Interfaces de streaming por lotes, jamás vídeo completo.** 2 h de
   profundidad 1080p float32 son ~1,4 TB: `process_chunk(lote de 8-48 frames)`
   con contrapresión (cola de tamaño 1) y RAM adaptativa, como siempre hizo el
   runner. `ChunkCtx` transporta fps, índice de chunk, cancelación cooperativa
   y presupuesto de RAM.
4. **La selección viaja en `cfg.engines` y Node la resuelve ANTES de hashear**
   el workdir: motor distinto ⇒ workdir distinto (reanudación correcta). El
   manifest de reanudación es ahora v2 e incluye los motores usados; uno v1 se
   acepta una única vez y se reetiqueta.
5. **Instalación por motor**: `setup.ps1 -Engine <ids>` lee los manifests
   (pip con `worker/constraints.txt`, clones a commit fijo, pesos HF; lo
   gated se comprueba ANTES de descargar nada). `-AI/-DML/-HQ/-All` quedan
   como alias. Venv aislado opcional por motor (`"venv": "isolated"` →
   `.venv-engines/<id>`, resuelto por job en `server/utils/python.ts`).

## Motores incluidos

| id | etapa | computo | notas |
|---|---|---|---|
| `depth_vda` | depth | CUDA | Video Depth Anything; ventana temporal 32/8 nativa |
| `depth_da2_onnx` | depth | DML/CPU | DA2 por frame + estabilizador EMA anti-pumping (`depth_smooth`) |
| `stereo_fast` | stereo | cualquiera | warp DIBR z-buffer; relleno por vecino (streaking leve) |
| `stereo_fast_telea` | stereo | cualquiera | **HQ-lite**: warp + `cv2.inpaint(TELEA)` en las bandas de desoclusión. Sin CUDA ni pesos gated |
| `stereo_sc_svd` | stereo | CUDA | StereoCrafter+SVD (gated). Sigue siendo la máxima calidad |

## Alternativas evaluadas y descartadas (con veredicto)

- **ZoeDepth / UniDepth / Metric3D** — profundidad métrica por-frame: la
  escala se descarta en la normalización relativa y el flicker produce
  *pumping* estereoscópico. Retroceso claro.
- **DepthCrafter** — excelente consistencia temporal pero basado en el mismo
  SVD gated que se quiere evitar, CUDA-only y ~50-100× más lento que VDA.
  Contradice la motivación.
- **LaMa / MAT / ZITS como inpainting** — por-frame ⇒ flicker estructurado en
  vídeo; MAT/ZITS además CUDA-céntricos y pensados para agujeros grandes
  (aquí son bandas de ≤19 px a 1080p con divergence 2.0). LaMa solo sería
  viable con propagación temporal (proyecto aparte). El video-inpainting real
  (ProPainter, E2FGVI) es CUDA-only y licencia no comercial: candidato a
  motor addon futuro para máquinas NVIDIA.
- **Depth Anything V3** — único candidato serio a vigilar: si aparece export
  ONNX, entra como *swap* dentro de `depth_da2_onnx` (mapear a `da3_*.onnx`),
  no requiere arquitectura nueva.
- **Interfaces `process(video) → Promise<DepthVideo>`** — inviables por
  memoria y porque rompen reanudación/cancelación. Rechazadas.

Claves de contexto que justifican HQ-lite: los huecos de desoclusión son
bandas estrechas (≤ ~19 px a 1080p), y el Half-SBS final hace downscale
horizontal ×2 justo donde viven esos artefactos — gran parte de la diferencia
SVD-vs-Telea desaparece en la TV. Toda comparativa de calidad debe hacerse
sobre el Half-SBS final, no sobre frames intermedios.

## Cómo escribir un motor

1. Crea `worker/engines/<id>/` con `manifest.json` (valida contra
   `manifest.schema.json`; `id` = nombre de la carpeta), `probe.py`
   (`def probe(models_dir) -> {"available", "missing", "detail"}`) y
   `engine.py` (`def create(cfg, models_dir) -> motor`).
2. El motor implementa el protocolo de su etapa (`engine_api.v1`):
   `process_chunk(frames, ctx)` para depth, `process(frames, depths, ctx)`
   para estéreo; consulta `ctx.cancel` entre sub-lotes; si mantiene estado
   temporal, reinícialo cuando cambie `ctx.chunk_idx`.
3. Declara en el manifest tus `weights` (con `commit` pineado en los git y
   `gated: true` donde toque), `requirements` propios, `estimator.base_fps`
   como semilla y `cfg_schema` para tus campos de cfg.
4. Nada más: `detect.py` te descubre y sondea, `/api/health` te expone, la UI
   te lista en el selector de modo, el estimador te estima (semilla →
   calibración real tras la primera conversión) y `setup.ps1 -Engine <id>` te
   instala.

## Versionado del contrato

`engine_api.API_VERSION` sigue semver: cambios aditivos (campo nuevo en
`ChunkCtx` con default) = minor; ruptura de firma = `v2.py` conviviendo con
`v1.py` y un shim v1→v2 en el registry durante al menos una major. El
`manifest_version` evoluciona aparte (lo leen también Node y PowerShell).
