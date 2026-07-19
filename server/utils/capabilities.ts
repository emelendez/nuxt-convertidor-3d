// Deteccion de capacidades para /api/health y /api/estimate.
//
//  - SIMULATE: valores ficticios (GPU RTX 4070 simulada, todo disponible).
//  - real con worker Python: el sondeo AUTORITATIVO lo hace worker/detect.py
//    (tiene torch/onnxruntime/ffmpeg y sabe si hay CUDA, DirectML o solo CPU,
//    que encoder funciona y que backend de profundidad existe). Node lo cachea.
//  - real sin worker Python (venv no instalado): heuristico Node conservador
//    (NVIDIA por nvidia-smi -> CUDA; en otro caso CPU, sin poder detectar DML).
import { existsSync } from 'node:fs'
import { cpus, totalmem } from 'node:os'
import { join } from 'pathe'
import { APP_NAME, APP_VERSION, ROOT_DIR, isSimulate } from './config'
import { execCapture, which } from './proc'
import { pythonExe, venvReady, workerEnv } from './python'
import { matchGpu, type ComputeInfo, type GpuInfo } from './estimator'

export interface Components {
  ffmpeg: boolean
  ffprobe: boolean
  nvenc: boolean
  encoder: string | null
  gpu: boolean
  depth: string | null       // 'vda' | 'onnx' | null
  depth_vda_s: boolean
  stereo_fast: boolean
  stereo_hq: boolean
}

// Motor de IA addon reportado por worker/detect.py (worker/engines/<id>/).
export interface EngineInfo {
  id: string
  stage: 'depth' | 'stereo' | 'inpaint'
  label: string
  description?: string | null
  available: boolean
  missing: string[]
  detail?: string | null
  requires_compute: string[]
  gated?: boolean
  licenses?: string[]
  estimator?: { base_fps?: Record<string, number>, vram_gb?: Record<string, number> } | null
  cfg_schema?: Record<string, any> | null
}

export interface Capabilities {
  compute: ComputeInfo
  components: Components
  missing: { depth: string[], stereo_hq: string[] }
  gpus: GpuInfo[]
  engines?: EngineInfo[]   // ausente si el worker Python no esta instalado
  source: 'simulate' | 'python' | 'node'
}

// GPUs NVIDIA via nvidia-smi (sin pynvml). En SIMULATE, una ficticia.
export async function detectGpus(): Promise<GpuInfo[]> {
  if (isSimulate()) {
    return [matchGpu({ name: 'NVIDIA GeForce RTX 4070 (simulada)', vram_gb: 12.0, driver: '—', notes: [] })]
  }
  const r = await execCapture('nvidia-smi',
    ['--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
    { timeoutMs: 10000 })
  if (!r.ok) return []
  return r.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const [name, mem, driver] = line.split(',').map(s => s.trim())
    return matchGpu({ name, vram_gb: Math.round((Number(mem) / 1024) * 10) / 10, driver, notes: [] })
  })
}

// ── capacidades: simulacion / Python / heuristico Node ──────────────────────
async function simulateCapabilities(): Promise<Capabilities> {
  const cpuThreads = cpus().length
  const ramGb = Math.round(totalmem() / 1024 ** 3)
  return {
    compute: { kind: 'cuda', name: 'RTX 4070 (simulada)', notes: [], cpu_threads: cpuThreads, ram_gb: ramGb, amf: false },
    components: {
      ffmpeg: true, ffprobe: true, nvenc: true, encoder: 'hevc_nvenc', gpu: true,
      depth: 'vda', depth_vda_s: true, stereo_fast: true, stereo_hq: true,
    },
    missing: { depth: [], stereo_hq: [] },
    gpus: await detectGpus(),
    engines: [
      { id: 'depth_vda', stage: 'depth', label: 'Video Depth Anything (CUDA)', available: true, missing: [], requires_compute: ['cuda'] },
      { id: 'depth_da2_onnx', stage: 'depth', label: 'Depth Anything V2 (ONNX, DirectML/CPU)', available: true, missing: [], requires_compute: [] },
      { id: 'stereo_fast', stage: 'stereo', label: 'Rápido (warp DIBR)', available: true, missing: [], requires_compute: [] },
      { id: 'stereo_fast_telea', stage: 'stereo', label: 'HQ-lite (warp + relleno Telea)', available: true, missing: [], requires_compute: [], estimator: { base_fps: { '1080p': 5.0, '4k': 1.3 } } },
      { id: 'stereo_sc_svd', stage: 'stereo', label: 'Calidad (StereoCrafter + SVD)', available: true, missing: [], requires_compute: ['cuda'], gated: true },
    ],
    source: 'simulate',
  }
}

async function nodeCapabilities(): Promise<Capabilities> {
  const [gpus, hasFfmpeg, hasFfprobe] = await Promise.all([
    detectGpus(), which('ffmpeg'), which('ffprobe'),
  ])
  const cpuThreads = cpus().length
  const ramGb = Math.round(totalmem() / 1024 ** 3)
  const cuda = gpus.length > 0
  const compute: ComputeInfo = {
    kind: cuda ? 'cuda' : 'cpu',
    name: gpus[0]?.name || cpus()[0]?.model || 'CPU',
    notes: cuda ? [] : ['Worker Python no instalado: no se puede sondear la GPU integrada (DirectML). Ejecuta scripts\\setup.ps1 -Auto y reinicia.'],
    cpu_threads: cpuThreads, ram_gb: ramGb, amf: false,
  }
  return {
    compute,
    components: {
      ffmpeg: hasFfmpeg, ffprobe: hasFfprobe,
      nvenc: cuda, encoder: hasFfmpeg ? (cuda ? 'hevc_nvenc' : 'libx265') : null,
      gpu: cuda,
      depth: cuda ? 'vda' : null, depth_vda_s: false,
      stereo_fast: false, stereo_hq: false,
    },
    missing: {
      depth: ['Worker Python no instalado (scripts\\setup.ps1 -Auto)'],
      stereo_hq: cuda ? [] : ['Requiere GPU NVIDIA con CUDA'],
    },
    gpus,
    source: 'node',
  }
}

async function pythonCapabilities(): Promise<Capabilities> {
  const cli = join(ROOT_DIR, 'worker', 'detect.py')
  if (!venvReady() || !existsSync(cli)) throw new Error('worker Python no disponible')
  const r = await execCapture(pythonExe(), [cli],
    { cwd: ROOT_DIR, env: workerEnv(), timeoutMs: 120000, maxBuffer: 4 * 1024 * 1024 })
  const line = r.stdout.trim().split(/\r?\n/).filter(Boolean).pop() || ''
  let data: any
  try { data = JSON.parse(line) } catch {
    throw new Error('sondeo sin salida JSON: ' + (r.stderr.slice(-300) || 'desconocido'))
  }
  if (data.error) throw new Error(String(data.error))
  if (!data.compute || !data.components) throw new Error('sondeo incompleto')
  return { ...data, source: 'python' }
}

// Cache en memoria (equivale al lru_cache de detect_compute en Python). TTL para
// auto-sanar si se instala el worker con el servidor ya arrancado.
let _cache: { at: number, value: Capabilities } | null = null
let _inflight: Promise<Capabilities> | null = null
const TTL_MS = 5 * 60 * 1000

export async function getCapabilities(force = false): Promise<Capabilities> {
  if (isSimulate()) return simulateCapabilities()
  const now = Date.now()
  if (!force && _cache && now - _cache.at < TTL_MS) return _cache.value
  if (_inflight) return _inflight
  _inflight = pythonCapabilities()
    .catch(() => nodeCapabilities())               // sin worker: heuristico
    .then((value) => { _cache = { at: Date.now(), value }; _inflight = null; return value })
  return _inflight
}

export async function getHealth(settings: unknown) {
  const cap = await getCapabilities()
  return {
    app: APP_NAME,
    version: APP_VERSION,
    simulate: isSimulate(),
    compute: cap.compute,
    components: cap.components,
    missing: cap.missing,
    gpus: cap.gpus,
    engines: cap.engines ?? [],
    // El worker de IA (venv) esta instalado salvo en el heuristico 'node' (sin
    // venv). En simulacion se reporta como presente. La UI deshabilita/guia
    // "Generar demo"/"Convertir" cuando es false.
    worker_installed: cap.source !== 'node',
    settings,
  }
}
