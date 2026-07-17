# Convertidor 3D

Webapp **100 % local** (sin nube, sin subir ficheros a terceros) que convierte películas
MKV 2D (4K HEVC o 1080p) a **3D estereoscópico Side-by-Side** para televisores LG 3D
pasivos, usando estimación de profundidad por IA.

- **UI + servidor:** Nuxt 4 + Nuxt UI 4 sobre Nitro. Un único runtime Node sirve la
  interfaz y la API en `http://127.0.0.1:8765`.
- **IA:** worker en Python (PyTorch / ONNX Runtime) invocado como subproceso, un
  proceso por trabajo. Node orquesta la cola; Python solo computa.
- **Idioma:** toda la interfaz está en español.

## Características

- Asistente de 4 pasos: seleccionar película → configurar → demo de 60 s → conversión completa.
- Estimación de profundidad con **Video Depth Anything** (CUDA) o **Depth Anything V2 ONNX**
  (DirectML/CPU) con selección automática según el hardware.
- Dos modos de estéreo: **rápido** (warp DIBR) y **calidad** (splatting + inpainting, requiere CUDA).
- Codificación HEVC por hardware (NVENC → AMF → x265 como cascada de respaldo) y
  tone-mapping HDR→SDR (Dolby Vision incluido).
- **Reanudable:** la conversión se trocea por escenas; si se interrumpe, los chunks
  completados se reutilizan al relanzar el mismo trabajo.
- Previsualización 3D en el navegador (SBS, anaglifo, entrelazado) y cola de trabajos
  con progreso en tiempo real (SSE).
- **Modo red:** acceso opcional desde otros dispositivos de la LAN protegido por PIN,
  con subida y descarga de ficheros en streaming.

## Requisitos

| Componente | Detalle |
|---|---|
| SO | Windows 10/11 |
| Node.js | 20 o superior (para la webapp) |
| Python | 3.10+ con venv (para el worker de IA) |
| FFmpeg | build **full** (con `zscale`); `setup.ps1` lo instala en `tools/ffmpeg` |
| GPU | NVIDIA (CUDA, recomendado) o cualquier GPU DX12 (DirectML); CPU como último recurso |
| TV | LG 3D pasivo: activar el modo 3D manualmente (botón 3D → Side by Side) |

> Salida óptima para estas TVs: **Half-SBS 4K (3840×2160)**. El Full-SBS 4K excede el
> decodificador de esos paneles y solo se ofrece con advertencia (PC/VR).

## Instalación

Instalación por niveles con PowerShell (desde la raíz del proyecto):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1        # Node + build + FFmpeg + venv base
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -DML   # sin NVIDIA: torch CPU + ONNX DirectML
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -AI    # + PyTorch CUDA + Video Depth Anything
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -All   # + StereoCrafter (modo calidad HQ)
```

Los directorios `data/`, `models/`, `tools/` y `.venv/` no viajan con el repositorio:
los crea/descarga `setup.ps1`.

## Uso

```bat
run.bat
```

Arranque portable: regenera `node_modules`/build si faltan, lanza el servidor y abre el
navegador. Después, el asistente guía los 4 pasos; la pestaña **Trabajos** muestra la
cola, el progreso y las conversiones completadas (previsualizar / descargar / borrar).

Los MKV convertidos van al almacén interno `data/conversions` (configurable como
`output_dir` en `data/settings.json`, p. ej. un disco de medios).

### Modo red (LAN)

Por defecto `run.bat` expone la app en la red local protegida por un **PIN** que se
autogenera y se imprime en consola junto a las URLs (`http://<ip>:8765/?pin=<PIN>`),
creando además la regla de firewall necesaria. Desde otro dispositivo se puede subir un
MKV, lanzar conversiones y descargar el resultado. Con `-SoloLocal` el servidor escucha
solo en `127.0.0.1` sin PIN.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -SoloLocal
```

## Desarrollo

```powershell
npm run dev        # Vite HMR en http://127.0.0.1:8765
npm run build      # build de producción
npm run preview    # node .output/server/index.mjs

# sin GPU/FFmpeg: pipeline simulado claramente etiquetado (SIMULACIÓN)
$env:CONVERTIDOR3D_SIMULATE = "1"; npm run dev
```

La guía técnica detallada (arquitectura, contrato Node↔Python, convenciones y trampas
conocidas) está en [AGENT.md](AGENT.md).

## Arquitectura (resumen)

```
Navegador ── HTTP + SSE ──▶ Servidor Nitro (Nuxt 4): UI + API + cola de trabajos
                                 │  spawn por trabajo (JSON-lines por stdout)
                                 ▼
                            Worker Python: probe → escenas → decode (ffmpeg)
                              → profundidad (IA) → estéreo → SBS → encode → mux
```

Nunca se escriben frames intermedios a disco: todo circula por pipes y memoria en lotes
adaptativos a la RAM disponible.

## Licencia

Este proyecto se distribuye bajo la licencia [MIT](LICENSE).
