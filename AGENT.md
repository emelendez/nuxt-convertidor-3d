# AGENT.md - Convertidor 3D (Nuxt 4 + Nitro + worker Python)

Guia para agentes de IA que trabajen en este repositorio.

## Que es

Reescritura **hibrida** del Convertidor 3D: una webapp **100 % local** (sin nube,
sin subida de ficheros) que convierte peliculas MKV 2D (4K HEVC o 1080p) a 3D
estereoscopico Side-by-Side para televisores LG 3D pasivos.

- **UI + servidor: Nuxt 4 + Nuxt UI 4 sobre Nitro (Node/TypeScript).** Un unico
  runtime a la escucha (Node en 127.0.0.1:8765): sirve la SPA y expone la API.
- **IA: worker Python** (el pipeline del proyecto original, intacto) invocado por
  **subproceso, un proceso por trabajo**. Node orquesta; Python solo computa.

Idioma de la UI, los comentarios y los mensajes: **espanol**.

**Proyecto hermano de solo lectura:** `D:\WEBAPPS\convertidor-3d` (la version
original 100 % Python; NO se toca). `worker/backend/` nacio como copia
verbatim de su pipeline; desde 2026-07-18 es un **fork deliberado** (ver
`docs/adr-motores.md`): el codigo es propio y evoluciona aqui. `setup.ps1`
puede seguir copiando de alli FFmpeg y modelos.

**Motores de IA como addons:** las etapas de profundidad/estereo son motores
intercambiables en `worker/engines/<id>/` (manifest + probe + engine) sobre el
contrato `worker/engine_api/` y el registro `worker/engine_registry.py`. La
seleccion viaja en `cfg.engines` (la resuelve Node ANTES de hashear el
workdir) y la UI/estimador/instalador los descubren via `detect.py` ->
`/api/health`. Guia completa: `docs/adr-motores.md`.

## Arranque y comandos

```powershell
# arranque portable (regenera node_modules/build si faltan; abre el navegador)
run.bat

# instalacion por MOTOR (lee worker/engines/<id>/manifest.json)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Engine depth_da2_onnx,stereo_fast_telea
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -ListEngines   # tabla de motores, sin instalar
# alias retrocompatibles (niveles clasicos)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1        # Node + build + FFmpeg + venv base
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -DML   # sin NVIDIA: torch CPU + ONNX DirectML (+ telea)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -AI    # + PyTorch CUDA + Video Depth Anything
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -All   # + StereoCrafter (HQ; SVD es GATED: exige HF_TOKEN)
# -Yes = desatendido (sin prompts); log en .cache/setup-*.log

# desarrollo (Vite HMR, http://127.0.0.1:8765)
npm run dev

# produccion (build + servir)
npm run build
npm run preview            # = node .output/server/index.mjs

# desarrollo sin GPU/FFmpeg: pipeline falso claramente etiquetado (SIMULACION)
$env:CONVERTIDOR3D_SIMULATE = "1"; npm run dev
```

### Configuracion por entorno (runtime, sin rebuild)

Fuente idiomatica: `runtimeConfig.convertidor3d` (nuxt.config.ts) con override
en runtime via variables `NUXT_*`; las legacy `CONVERTIDOR3D_*` siguen
funcionando como fallback (shim en `server/utils/config.ts`, unico modulo que
lee entorno). El worker Python recibe SIEMPRE los nombres `CONVERTIDOR3D_*`
(contrato propio de `worker/backend/config.py`).

| Ajuste | Variable Nuxt | Legacy (fallback) | Default runtime |
|---|---|---|---|
| Modo simulacion | `NUXT_CONVERTIDOR3D_SIMULATE=true` | `CONVERTIDOR3D_SIMULATE=1` | off |
| Carpeta de datos | `NUXT_CONVERTIDOR3D_DATA_DIR` | `CONVERTIDOR3D_DATA` | `<raiz>/data` |
| Carpeta de modelos | `NUXT_CONVERTIDOR3D_MODELS_DIR` | `CONVERTIDOR3D_MODELS` | `<raiz>/models` |
| Interprete Python | `NUXT_CONVERTIDOR3D_PYTHON_EXE` | `CONVERTIDOR3D_PYTHON` | `.venv` del proyecto |
| PIN acceso remoto | `NUXT_CONVERTIDOR3D_PIN` | `CONVERTIDOR3D_PIN` | vacio = remoto deshabilitado |
| Puerto/host | `NITRO_PORT` / `NITRO_HOST` (o `PORT`/`HOST`) | — | 8765 / lo fija start.ps1 |

### Modo red (verificado E2E 2026-07-17)

`run.bat`/`start.ps1` exponen la app EN LA RED por defecto (`0.0.0.0`) con PIN:
si no llega por `-Pin` ni por env, se autogenera (8 chars, alfabeto sin
ambiguos) y se imprime junto a las URLs `http://<ip>:8765/?pin=<PIN>`. Ademas
crea la regla de firewall `Convertidor3D-8765` (solo perfiles domain/private;
sin admin imprime el comando para consola elevada). `-SoloLocal` = 127.0.0.1
clasico sin PIN. La UI local muestra las URLs+PIN en el popover wifi del header.

Seguridad (disenada para IP publica RIPE — la red institucional lo es):

- **Fail-closed** (`server/middleware/auth.ts`): remoto sin PIN configurado =
  403 a todo; `?pin=` valido una vez -> cookie HttpOnly con el SHA-256 del PIN
  (nunca el PIN) -> SSE/`<video>`/`<a download>` funcionan solos. Navegacion
  sin auth -> redirect a `/pin` (HTML autocontenido, `server/routes/pin.get.ts`).
  Throttling en memoria: 10 PINs malos/15 min por IP -> 429 (la cookie valida
  sigue funcionando). Local (`isLocal`) esta siempre exento.
- **Pivote cerrado**: cambiar `output_dir` via POST /api/settings es SOLO LOCAL
  — es la base de `assertWithinOutputDir`; un remoto que la moviera a `C:\`
  leeria todo el disco via descarga. No relajar jamas.
- **Acciones de escritorio del servidor** solo-local: `open-output-dir`
  (Explorer). El dialogo nativo (`browse.post.ts`) se ELIMINO: lo sustituye el
  explorador web `GET /api/fs/list` + `app/components/FileBrowser.vue` (lista
  unidades/carpetas/videos del disco DEL SERVIDOR; igual en local y remoto).
- **Descarga** `GET /api/output-files/download?path=` — attachment con
  Range/206 (reanudable; `parseByteRange` en fileActions). Guardas: solo
  `.mkv` + `assertWithinOutputDir`. Boton "Descargar" en Trabajos > Completadas.
- **Subida remota** `PUT /api/upload?name=` — streaming directo a
  `data/uploads/` (nunca multipart en memoria: son GB); basename+saneo del
  nombre; solo extensiones de video. UI: `UFileUpload` en el paso 1, SOLO
  visible para clientes remotos; progreso via XHR. No se auto-borra al convertir.
- La UI se adapta con `client_is_local` (y `lan_urls`/`remote_pin`, este solo
  para locales) que devuelve `/api/health`; getter `store.isLocalClient`.
- Riesgos aceptados y documentados en el plan: sin TLS (PIN/contenido en claro
  en la LAN; mitigacion = perfiles de firewall + PIN aleatorio; reverse-proxy
  TLS como mejora futura), sin identidad por cliente (PIN compartido: cualquiera
  con el ve/cancela/borra), descargar un MKV a medio muxar sale truncado.

### Almacen de conversiones (`data/conversions`)

Los MKV convertidos (demos y completos) van al **almacen interno**
`data/conversions` (relativo al proyecto: viaja con la carpeta, gitignored).
Es un area de staging gestionada desde la UI en Trabajos > Completadas:
previsualizar / **Descargar** (attachment con Range/206, tambien desde otros
dispositivos de la red — ver "Modo red") / borrar (definitivo).

- Configurable: `output_dir` en `data/settings.json` (p. ej. un disco de
  medios como `D:\PELICULAS\3D`). Node lo resuelve SIEMPRE contra la raiz del
  proyecto (`config.outputDir()`), asi que valen relativas y absolutas.
- **Contrato con el worker Python:** el worker lee `output_dir` de
  `CONVERTIDOR3D_DATA/settings.json` por su cuenta y su default propio es
  `~/Videos` (distinto). Por eso `bootstrap.ts` MATERIALIZA `settings.json`
  al arrancar si falta; el worker resuelve la relativa contra su cwd, que
  `worker.ts` fija a la raiz. No romper ese contrato.

No hay suite de tests todavia. Verificacion: modo simulacion para UI/API/cola/SSE
(sin GPU/FFmpeg); maquina con GPU NVIDIA o iGPU DX12 + FFmpeg para el pipeline real.
Patron de verificacion headless usado aqui: conducir Chrome por CDP con Node.

## Arquitectura y flujo de datos

```
Navegador (Chrome)
   |  HTTP + SSE
Servidor Nitro (Nuxt 4)  -- sirve UI (Nuxt UI) + API en server/api/*
   |  spawn por job:  python worker/cli.py --job <spec>   (stdout = JSON-lines)
Worker Python CLI  -- RunnerContext.run():
   MKV -> probe -> scenes (chunks por corte) -> decode (ffmpeg NVDEC -> numpy)
       -> depth (Video Depth Anything / Depth Anything V2 ONNX)
       -> stereo_fast (warp DIBR) o stereo_hq (splatting + inpainting SVD)
       -> sbs -> encode (hevc_nvenc/amf/x265 por chunk) -> concat + mux
   |  ffmpeg (pipes) . torch/onnxruntime . numpy
tools/ffmpeg  .  models/   (assets pesados; env CONVERTIDOR3D_MODELS/DATA)
```

- **Node** posee: cola de jobs, estimador, deteccion GPU/compute, probe (ffprobe),
  health, acciones de fichero (abrir/borrar/preview), settings, SSE y servir la UI.
- **Python** queda reducido a worker sin servidor: recibe el jobspec, ejecuta el
  pipeline y **emite progreso por stdout**. El pipeline (`worker/backend/pipeline/*`)
  NO se reescribe: es copia verbatim del proyecto original.
- **Nunca** se escriben frames intermedios a disco: todo va por pipes/memoria en
  lotes adaptativos a RAM. Manifest JSON por chunk -> **reanudable**.
- **Cola secuencial** (una GPU): un job en curso, resto en cola. Cancelacion y
  eventos a la UI por **SSE** (`/api/events`; reconexion nativa de EventSource).

### Contrato del worker (Node <-> Python)

- **Invocacion:** Node hace `spawn(python, ['worker/cli.py', '--job', <ruta.json>])`
  con el entorno `CONVERTIDOR3D_DATA`/`CONVERTIDOR3D_MODELS` (para compartir
  `data/` y `models/` con Node) y `PYTHONUTF8=1`.
- **Jobspec** (`<workdir>/jobspec.json`, lo escribe Node): `job_id, source, probe,
  cfg, segment_start, segment_duration, is_demo, workdir, simulate`. Dentro de
  `cfg` viaja `engines: {depth, stereo}` con los motores YA RESUELTOS por Node
  (jamas 'auto': entra en el hash del workdir). Un jobspec legacy sin
  `engines` sigue funcionando (mapper en `runner._resolve_engines`).
- **Manifest de reanudacion v2** (`<workdir>/manifest.json`): incluye
  `engines` ademas de `cfg`; reanudar exige igualdad de ambos (los chunks de
  motores distintos no se mezclan). Un manifest v1 se acepta una vez y se
  reetiqueta.
- **workdir determinista:** lo calcula **Node** (`sha1` de [source,cfg,kind,segmento]
  en `jobs.ts:canonical`) y lo pasa en el jobspec; el worker lo usa tal cual (NO
  re-hashea). Asi la reanudacion sobrevive a reinicios. NOTA: el hash de Node
  (sin espacios) NO coincide con el de Python (`json.dumps` con espacios); por eso
  la fuente de verdad es Node.
- **Progreso:** el worker escribe **una linea JSON por evento** a stdout:
  `{"type":"progress", stage, frames_done, frames_total, fps, chunk, chunks_total,
  eta_s, thumbnail, message}`, luego `{"type":"done","output":<ruta>}` o
  `{"type":"cancelled"}` o `{"type":"error","message":...}`.
- **Canal limpio:** `cli.py` reserva el stdout real para ese JSON y **desvia a
  stderr** cualquier print de librerias (torch/tqdm/...) para no corromperlo.
- **Cancelacion:** Node escribe `cancel\n` en el stdin del worker (respaldo:
  `child.kill()` tras 8 s); un hilo vigilante de `cli.py` activa el
  `threading.Event` del runner -> parada limpia (los chunks completos sobreviven).
  EOF de stdin NO cancela (evita cancelaciones espurias).

## Mapa de ficheros

| Ruta | Responsabilidad |
|---|---|
| `nuxt.config.ts` | modulos @nuxt/ui + @pinia/nuxt, `ssr:false` (SPA), colorMode por clase `dark`, host 127.0.0.1:8765 |
| `app/app.vue` | `<UApp>` + layout raiz; carga health e inicia `useJobEvents` |
| `app/layouts/default.vue` | cabecera (health badges, tema) + nav stepper (4 pasos) + boton Trabajos |
| `app/pages/{index,config,demo,convert,jobs}.vue` | asistente de 4 pasos + pestana Trabajos |
| `app/components/Preview3D.vue` | previsualizacion 3D reutilizable (SBS/Anaglifo/Entrelazado) |
| `app/components/FileBrowser.vue` | modal explorador del disco DEL SERVIDOR (sustituye al dialogo nativo) |
| `app/components/{HealthBadges,...}.vue` | componentes de UI |
| `app/composables/useApi.ts` | wrapper de `$fetch` con extraccion de error |
| `app/composables/useJobEvents.ts` | `EventSource('/api/events')` -> store; polling de output-files |
| `app/composables/useSbsRenderer.ts` | envuelve `renderer.js` (RAF, refs, fix de aspecto) |
| `app/stores/app.ts` | Pinia: estado global (probe, estimate, cfg, jobs, outputFiles) |
| `app/utils/renderer.js` | anaglifo/entrelazado: **WebGL2 primero** (WebGPU da negro en iGPU), matrices Dubois |
| `app/utils/mediainfo.js` | metadatos en cliente (WASM, opcional, degrada) |
| `server/api/*.ts` | API REST + SSE (h3), mapa 1:1 con el backend original |
| `server/utils/config.ts` | rutas, settings, flag SIMULATE, puerto 8765 |
| `server/utils/estimator.ts` | port fiel de `estimator.py` (BD de GPUs, matriz 42 combos) |
| `server/utils/capabilities.ts` | capacidades para health/estimate: delega el sondeo AUTORITATIVO (cuda/dml/cpu, encoder, backend de profundidad) en `worker/detect.py` y lo cachea; si no hay venv, heuristico Node (nvidia-smi -> cuda, si no cpu) |
| `server/utils/python.ts` | helpers para invocar el worker (interprete del venv, entorno compartido) |
| `server/utils/jobs.ts` | JobManager: cola, cancelacion, SSE, `workdir()` (hash) |
| `server/utils/worker.ts` | ejecucion de un job: simulacion (Node) o spawn del worker Python |
| `server/utils/probe.ts` | ffprobe -> metadatos |
| `server/utils/fileActions.ts` | output-files, preview H264 (ffmpeg), abrir/borrar, `parseByteRange` (Range/206), `writeStreamToFile` |
| `server/utils/security.ts` | solo-local (`assertLocal`) + anti path-traversal (`assertWithinOutputDir`) + throttling del PIN |
| `server/utils/net.ts` | thin adapter node:os -> URLs LAN para compartir |
| `server/utils/proc.ts` | thin adapter child_process (spawn/exec, todo async) — unico modulo de procesos |
| `server/utils/hash.ts` | SHA-1 y UUID con Web Crypto (workdir determinista, identico a node:crypto) |
| `server/middleware/auth.ts` | PIN fail-closed para remotos (cookie = SHA-256 del PIN) |
| `server/routes/pin.get.ts` | formulario de PIN autocontenido (fuera de la SPA) |
| `server/plugins/bootstrap.ts` | antepone `tools/ffmpeg/bin` al PATH + crea directorios |
| `worker/cli.py` | **entrypoint nuevo**: envuelve `RunnerContext`, emite JSON, cancela por stdin |
| `worker/detect.py` | **entrypoint nuevo**: sondeo de capacidades (cuda/dml/cpu, encoder, depth) + motores addon -> JSON para Node |
| `worker/engine_api/` | contrato v1 de motores (semver): `ChunkCtx`, protocolos, `ops.DibrWarper` (warp+mascara publico) |
| `worker/engine_registry.py` | descubrimiento/validacion/instanciacion de motores (importlib por ruta) |
| `worker/engines/<id>/` | un motor = manifest.json + engine.py + probe.py (+ requirements). Esquema: `engines/manifest.schema.json` |
| `worker/backend/` | pipeline Python — **fork deliberado** del proyecto original desde 2026-07-18 (antes verbatim; ver docs/adr-motores.md) |
| `worker/requirements*.txt` | base / -AI (CUDA) / -AI-cpu (DML) del worker; `constraints.txt` = limites pip compartidos |
| `docs/adr-motores.md` | ADR de la arquitectura de motores + guia "como escribir un motor" |
| `scripts/setup.ps1` | instalacion por niveles (Node + build + FFmpeg + venv) |
| `scripts/start.ps1` + `run.bat` | lanzador portable |
| `models/`, `tools/ffmpeg/`, `data/` | assets/datos (en .gitignore; los crea/copia setup.ps1) |

## Convenciones del codigo

- **TypeScript/Nitro:** handlers h3 en `server/api/`; utilidades en `server/utils/`
  (auto-import de Nitro). El acceso remoto lo gobierna el middleware de PIN
  (ver "Modo red"); las acciones de escritorio del servidor llevan `assertLocal`.
  Errores como `createError({statusCode, statusMessage})` -> viajan legibles a la UI.
- **Web-standard primero; Node confinado en thin adapters** (auditoria jul-2026):
  rutas con **pathe** (no `node:path`; tampoco `new URL` — aqui se manipulan rutas
  absolutas Windows arbitrarias); hashing con **Web Crypto** global
  (`crypto.randomUUID`, `crypto.subtle` en `utils/hash.ts` — SHA-1 identico a
  node:crypto: la reanudacion sobrevive); settings/calibration via
  **`useStorage('appdata')`** (fs-lite montado en runtime en bootstrap.ts sobre
  dataDir; `setItemRaw` con JSON pretty para que el worker Python y humanos lo
  lean; NO llamar al mount `data`: colisiona con el de Nitro y unstorage lanza);
  los previews se sirven devolviendo un **ReadableStream web** (`streamFile`).
  Adapters Node permitidos y unicos: `utils/proc.ts` (child_process, TODO async
  — los exec sincronos bloqueaban el event loop 10-30 s), `utils/fileActions.ts`
  (fs: stream/stat/mkdir), `utils/config.ts` (env/cwd/homedir), `utils/python.ts`
  (venv), os.cpus/totalmem en capabilities, y el PATH de ffmpeg en bootstrap.
- **Guarda anti path-traversal:** `assertWithinOutputDir()` (lanza 400) — es
  assert y no predicado a proposito: `!promesa` compila y desactivaria la guarda.
- **Estimador:** `estimateOne/estimateMatrix` son puros y sincronos; la
  calibracion se carga UNA vez por peticion y se pasa como parametro.
- **Frontend:** Vue 3 + Nuxt UI 4 (Tailwind v4 CSS-first, incluido). `ssr:false`
  (SPA: usa WebGPU/WebGL, `<video>`, `EventSource`, rutas de disco locales).
  Estado en Pinia (`app/stores/app.ts`). Texto de UI en espanol. El bucle RAF del
  renderer se gestiona en `useSbsRenderer` (refs + onUnmounted), nunca en el render.
- **Python (worker):** el pipeline es codigo del proyecto original; imports pesados
  (torch, diffusers, cv2, scenedetect) **perezosos** dentro de funciones. `cli.py`
  reconfigura stdout/stderr a UTF-8; el JSON de progreso puede llevar acentos.
- **Reutilizacion maxima:** `renderer.js` y `mediainfo.js` son copias intactas del
  proyecto original; `estimator.ts` es port fiel de `estimator.py` (misma matriz).

## Trampas conocidas

- **PowerShell 5.1 / codificacion (bug real, no reintroducir):** los `.ps1` deben
  ser **ASCII puro** (sin tildes ni `-`/guiones tipograficos): PS 5.1 lee los .ps1
  sin BOM como ANSI y los caracteres multi-byte rompen el parser. El texto de la UI
  web (HTML/JS/JSON) si puede llevar tildes y simbolos.
- **Canal JSON del worker:** cualquier print a stdout de una libreria corromperia
  el stream; `cli.py` ya desvia el stdout de librerias a stderr. No escribir a
  stdout desde el pipeline.
- **Cancelacion en Windows:** el `kill` duro no dispara SIGTERM de forma fiable ->
  la cancelacion va por la linea `cancel` en stdin; el kill es solo respaldo.
- **stdin heredado = deadlock de ffmpeg (bug REAL cazado en el primer E2E,
  2026-07-17, no reintroducir):** los subprocesos heredan el fd 0 del worker,
  que es el PIPE de cancelacion de Node; ffmpeg sin `-nostdin` se queda
  BLOQUEADO leyendolo para siempre (el mux final se congelo 35 min con CPU 0 y
  el fichero casi completo). En el proyecto original no pasaba porque uvicorn
  corria con stdin de consola. Fix: `_shield_stdin()` en `cli.py` (duplica el
  pipe para el hilo de cancelacion y pone NUL en el fd 0 -> TODOS los ffmpeg
  del pipeline heredan NUL sin tocar `worker/backend/`), idem en `detect.py`,
  y `-nostdin` en el ffmpeg de previews de Node (fileActions). Si se anade
  cualquier spawn nuevo que herede stdin, mantener este escudo.
- **workdir hash:** la fuente de verdad es Node; no re-hashear en Python (los
  formatos de serializacion difieren en espacios). `cfg.engines` DEBE llegar
  resuelto desde Node (nunca 'auto'): forma parte del hash y de la identidad
  de reanudacion.
- **Motores nuevos:** un motor no es solo codigo — necesita manifest valido
  (id = carpeta), probe, claves de calibracion propias y, si trae pesos git,
  commit pineado. NO tocar las claves de calibracion legacy de los motores
  clasicos (warp/inpaint/depth): hay maquinas con calibracion escrita.
- **Maquina de desarrollo sin GPU NVIDIA ni FFmpeg:** el pipeline real
  (depth/stereo_hq/encode) esta escrito y su contrato verificado, pero valida las
  firmas contra los repos clonados (`models/Video-Depth-Anything`,
  `models/StereoCrafter`) al integrarlo en hardware real.
- **Modo simulacion** (`CONVERTIDOR3D_SIMULATE=1`): en Node, `worker.ts` corre una
  simulacion propia (no lanza Python); acepta rutas inexistentes. No anadir logica
  de negocio que dependa de el.
- **Build con Node 26:** `nitro.externals.trace: false` en nuxt.config.ts es
  deliberado — el trazado de dependencias de @vercel/nft revienta (EISDIR en
  readlink de ficheros normales). La app corre siempre desde su carpeta con
  `node_modules` presente, asi que el trazado no aporta nada. No reactivarlo.
- **FFmpeg** debe ser build **full** (con `zscale`) para el tone-mapping HDR->SDR.
  Va embebido en `tools/ffmpeg/bin` (el plugin de Nitro lo antepone al PATH y se
  hereda al worker Python).
- **LG 3D pasivo:** el SBS se activa **manualmente** en la TV (boton 3D -> Side by
  Side). Optimo: **Half-SBS 4K (3840x2160)**; Full-SBS 4K excede el decodificador
  de esas TVs (solo con advertencia, para PC/VR). El flag Matroska `stereo_mode`
  se escribe igualmente (ayuda en Kodi/Plex).

## Estado y pendientes

Hecho y verificado (modo simulacion + contrato del worker): API completa, SSE,
matriz de estimaciones (identica a la de Python), 4 vistas del asistente + pestana
Trabajos, previsualizacion 3D (SBS/anaglifo/entrelazado con aspecto correcto),
temas claro/oscuro, cola con progreso/cancelacion. Worker Python: `cli.py` probado
en simulacion (contrato JSON, UTF-8, done, cancelacion por stdin). Empaquetado:
`setup.ps1`, `start.ps1`/`run.bat`.

**Fallback sin CUDA verificado** (en un equipo real sin NVIDIA): `detect.py`
reporta `kind=dml` + `depth=onnx` + cascada de encoders; `/api/health` y
`/api/estimate` lo reflejan (estimacion fallback, modo Calidad rechazado). El
pipeline del worker ya enruta VDA(CUDA) -> Depth Anything V2 ONNX (DirectML/CPU)
y nvenc -> amf -> x265 automaticamente (codigo verbatim del original).

**E2E REAL verificado (2026-07-17, i5-13500 + UHD 770 DirectML, sin NVIDIA):**
demo de 60 s de un MKV 4K Dolby Vision EAC3-Atmos por el pipeline completo
(decode+tonemap -> DA2-S DirectML -> warp CPU -> Half-SBS -> x265 10-bit ->
remux) a ~0,85 fps globales. Salida verificada: HEVC 1920x1080 yuv420p10le,
`stereo_mode=left_right`, AAC 6ch, previews hevc+h264, servida por la API con
streams web. **Reanudacion verificada**: relanzar el mismo job tras un fallo
reutilizo los 10 chunks (28 min de IA) y completo en ~21 s. Calibracion local
escrita por el worker (`dml:depth:vda_s=0.91`, `dml:warp:1080p=10.23`).

**Modo red verificado (2026-07-17):** bateria E2E de 37 checks (PIN fail-closed,
throttling, guardas por origen, descarga byte-identica + Range 206/416, fs/list,
subida streaming con saneo, preview/borrado remotos, SSE) + 17 checks de UI por
CDP (local vs remoto) + demo creada desde el origen remoto con el worker
escribiendo en `data/conversions` (reanudacion ~30 s). Scripts de la bateria en
el scratchpad de la sesion (`test_red.mjs`, `shot_red.mjs`).

**Arquitectura de motores addon (2026-07-18, issue #4):** fork declarado de
`worker/backend/`; contrato `engine_api` v1 + registro + 5 motores builtin
(depth_vda, depth_da2_onnx con estabilizador temporal, stereo_fast,
stereo_fast_telea "HQ-lite" sin SVD/CUDA, stereo_sc_svd); manifest de
reanudacion v2 con identidad de motor; motores resueltos en Node antes del
hash; detect.py/health/estimador/UI descubren motores dinamicamente;
`setup.ps1 -Engine` instala por manifest (gated-aware, commits pineados,
constraints.txt, -Yes desatendido, log+freeze en .cache). Bugs reales
corregidos: `attempt_nvdec` indefinido en decode.py; venv sin pip;
EPERM de npm por procesos node residuales/OneDrive (reintento).

**E2E REAL verificado (2026-07-18, AMD Radeon iGPU DirectML, sin NVIDIA):**
`setup.ps1 -All -Yes` desatendido termina exit 0 (3 motores OK, 2 SALTADO
CUDA con razon; FFmpeg via winget); demo real de 10 s con
`depth_da2_onnx`(+estabilizador)+`stereo_fast_telea` por el pipeline completo
a 1,33 fps globales -> HEVC 1920x1080 `stereo_mode=left_right` via hevc_amf;
calibracion por motor escrita (`dml:stereo:stereo_fast_telea:1080p=2.24`);
reanudacion con manifest v2: relanzar el mismo job reutilizo el chunk (20 s
vs ~180 s). OJO: `nuxt build` NO ejecuta typecheck (no hay vue-tsc instalado)
— los errores de tipos solo se ven en runtime.

Pendiente: prueba en GPU NVIDIA/CUDA (modo Calidad incluido); pelicula completa
(no solo demo); comparativa visual Half-SBS de stereo_fast_telea vs stereo_fast
en TV real; i18n en/es. Mejora futura del modo red: TLS via reverse-proxy.
