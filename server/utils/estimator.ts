// Port de backend/core/estimator.py — modelo de coste + tablas estaticas.
// Sin numpy: es aritmetica pura. La calibracion local (fps medidos por el worker)
// sustituye los valores estaticos cuando existe; se carga UNA vez por peticion
// (loadCalibration) y se pasa como parametro: estimateOne/estimateMatrix son
// funciones puras y sincronas, fieles al port de Python.

export interface GpuInfo {
  name: string
  vram_gb: number
  driver: string
  scaler?: number
  known?: boolean
  notes: string[]
}

export interface ComputeInfo {
  kind: 'cuda' | 'dml' | 'cpu'
  name: string
  notes: string[]
  cpu_threads?: number
  ram_gb?: number
  amf?: boolean
}

export interface Estimate {
  proc_res: string
  depth_model: string
  mode: string          // 'fast' | 'hq' | id de motor addon (stereo_fast_telea, ...)
  inpaint_steps: number
  output: string
  demo_seconds: number
  full_seconds: number
  vram_needed_gb: number
  status: 'ok' | 'warn' | 'no'
  notes: string[]
  calibrated: boolean
}

// Motor de estéreo addon (de /api/health engines[]): lo minimo que el
// estimador necesita para estimar un motor que no conoce de fabrica.
export interface StereoEngineInfo {
  id: string
  label?: string
  requires_compute?: string[]
  estimator?: { base_fps?: Record<string, number> } | null
}

// mode legacy <-> id de motor: 'fast' y 'hq' son alias historicos de los dos
// motores clasicos; el resto de modes SON ids de motor tal cual.
export const MODE_TO_ENGINE: Record<string, string> = { fast: 'stereo_fast', hq: 'stereo_sc_svd' }
export function modeToEngine(mode: string): string { return MODE_TO_ENGINE[mode] ?? mode }
export function engineToMode(id: string): string {
  return id === 'stereo_fast' ? 'fast' : id === 'stereo_sc_svd' ? 'hq' : id
}

// ── BD de GPUs: escalador vs RTX 4090 ──────────────────────────────────────
export const GPU_DB: Record<string, number> = {
  'RTX 3060 Ti': 0.30, 'RTX 3060': 0.24,
  'RTX 3070 Ti': 0.39, 'RTX 3070': 0.37,
  'RTX 3080 Ti': 0.58, 'RTX 3080': 0.52,
  'RTX 3090 Ti': 0.67, 'RTX 3090': 0.63,
  'RTX 4060 Ti': 0.28, 'RTX 4060': 0.22,
  'RTX 4070 Ti SUPER': 0.56, 'RTX 4070 Ti': 0.52,
  'RTX 4070 SUPER': 0.48, 'RTX 4070': 0.42,
  'RTX 4080 SUPER': 0.67, 'RTX 4080': 0.65,
  'RTX 4090': 1.00,
  'RTX 5060 Ti': 0.32, 'RTX 5060': 0.26,
  'RTX 5070 Ti': 0.62, 'RTX 5070': 0.50,
  'RTX 5080': 0.81, 'RTX 5090': 1.50,
}
const LAPTOP_FACTOR = 0.70
const UNKNOWN_SCALER = 0.30

const DEPTH_FPS: Record<string, number> = { vda_s: 130.0, vda_b: 95.0, vda_l: 70.0 }
const DEPTH_4K_FACTOR = 0.90
const WARP_FPS: Record<string, number> = { '1080p': 110.0, '4k': 28.0 }
const HQ_INPAINT_FPS_8STEPS: Record<string, number> = { '1080p': 0.85, '4k': 0.22 }
const ENCODE_FPS: Record<string, number> = { hsbs_1080: 300.0, fsbs_1080: 150.0, hsbs_4k: 75.0, fsbs_4k: 37.0 }
const DECODE_FPS = 350.0
const OVERLAP_EFFICIENCY = 0.85
const SETUP_SECONDS = 120.0

const FALLBACK_DEPTH_FPS: Record<string, Record<string, number>> = {
  dml: { vda_s: 3.5, vda_b: 1.2, vda_l: 0.35 },
  cpu: { vda_s: 2.0, vda_b: 0.7, vda_l: 0.20 },
}
const FALLBACK_WARP_FPS: Record<string, number> = { '1080p': 3.0, '4k': 0.8 }
const FALLBACK_ENCODE_FPS: Record<string, Record<string, number>> = {
  amf: { hsbs_1080: 120.0, fsbs_1080: 60.0, hsbs_4k: 30.0, fsbs_4k: 15.0 },
  x265: { hsbs_1080: 12.0, fsbs_1080: 6.0, hsbs_4k: 3.0, fsbs_4k: 1.5 },
}
const FALLBACK_CPU_SCALE_REF_THREADS = 16

export const DEPTH_MODELS: Record<string, { label: string, license: string, comercial: boolean }> = {
  vda_s: { label: 'Small (28M)', license: 'Apache-2.0', comercial: true },
  vda_b: { label: 'Base (113M)', license: 'CC-BY-NC-4.0', comercial: false },
  vda_l: { label: 'Large (382M)', license: 'CC-BY-NC-4.0', comercial: false },
}
export const OUTPUTS: Record<string, Record<string, unknown>> = {
  hsbs_1080: { label: 'Half-SBS 1080p', res: '1920×1080', lg: true },
  hsbs_4k: { label: 'Half-SBS 4K', res: '3840×2160', lg: true, recomendado_lg: true },
  fsbs_1080: { label: 'Full-SBS 1080p', res: '3840×1080', lg: true },
  fsbs_4k: { label: 'Full-SBS 4K', res: '7680×2160', lg: false },
}

const DEPTH_ORDER = ['vda_s', 'vda_b', 'vda_l']
const OUTPUT_ORDER = ['hsbs_1080', 'hsbs_4k', 'fsbs_1080', 'fsbs_4k']

export function matchGpu(gpu: GpuInfo): GpuInfo {
  const name = gpu.name
  let bestKey: string | null = null
  for (const key of Object.keys(GPU_DB).sort((a, b) => b.length - a.length)) {
    if (new RegExp(escapeRe(key), 'i').test(name)) { bestKey = key; break }
  }
  if (bestKey) {
    gpu.scaler = GPU_DB[bestKey]
    gpu.known = true
    if (/laptop|mobile|max-q/i.test(name)) {
      gpu.scaler = round3(gpu.scaler * LAPTOP_FACTOR)
      gpu.notes.push('Variante portátil: rendimiento estimado ×0.7')
    }
  } else {
    gpu.scaler = UNKNOWN_SCALER
    gpu.known = false
    gpu.notes.push('GPU no catalogada: estimación conservadora; la calibración la ajustará')
  }
  return gpu
}

// Calibracion via useStorage('appdata') — en disco sigue siendo
// data/calibration.json (JSON plano): la ESCRIBE el worker Python tras cada
// conversion real; aqui solo se lee (saveCalibration existe por paridad con
// el port Python, sin call sites Node a dia de hoy).
export async function loadCalibration(): Promise<Record<string, number>> {
  try {
    const raw = await useStorage('appdata').getItem<Record<string, number>>('calibration.json')
    if (raw && typeof raw === 'object') return raw as Record<string, number>
  } catch { /* ilegible */ }
  return {}
}

export async function saveCalibration(measurements: Record<string, number>): Promise<void> {
  const current = { ...(await loadCalibration()), ...measurements }
  await useStorage('appdata').setItemRaw('calibration.json', JSON.stringify(current, null, 2))
}

function stageFps(key: string, base4090: number, scaler: number,
  cal: Record<string, number>, aiStage = true): [number, boolean] {
  if (key in cal) return [cal[key], true]
  return [aiStage ? base4090 * scaler : base4090, false]
}

function vramCheck(procRes: string, depthModel: string, mode: string, vram: number):
  [number, 'ok' | 'warn' | 'no', string[]] {
  const notes: string[] = []
  const depthNeed = ({ vda_s: 7.0, vda_b: 12.0, vda_l: 24.0 } as Record<string, number>)[depthModel]
  const depthMin = ({ vda_s: 4.0, vda_b: 8.0, vda_l: 13.0 } as Record<string, number>)[depthModel]
  let status: 'ok' | 'warn' | 'no' = 'ok'
  if (vram < depthNeed) {
    if (vram >= depthMin) {
      status = 'warn'
      notes.push('VRAM justa para el modelo de profundidad: ventana reducida (16 frames)')
    } else {
      return [depthNeed, 'no', ['VRAM insuficiente para el modelo de profundidad']]
    }
  }
  let need = depthNeed
  if (mode === 'hq') {
    const hqNeed = procRes === '1080p' ? 16.0 : 24.0
    const hqMin = procRes === '1080p' ? 12.0 : 16.0
    need = Math.max(need, hqNeed)
    if (vram < hqNeed) {
      if (vram >= hqMin) {
        status = 'warn'
        notes.push('Inpainting con downscale + tiling + chunks cortos (más lento)')
      } else {
        return [need, 'no', [`VRAM insuficiente para el inpainting de difusión (mínimo ${hqMin.toFixed(0)} GB en ${procRes})`]]
      }
    }
  }
  return [need, status, notes]
}

function estimateFallback(durationS: number, fps: number, compute: ComputeInfo,
  procRes: string, depthModel: string, mode: string, output: string,
  demoDurationS: number, cal: Record<string, number>, notes: string[],
  engines?: StereoEngineInfo[]): Estimate {
  const kind = compute.kind // 'dml' | 'cpu'
  const threads = compute.cpu_threads || 8
  const cpuScale = Math.min(threads / FALLBACK_CPU_SCALE_REF_THREADS, 1.5)

  const engineId = modeToEngine(mode)
  const engineInfo = engines?.find(e => e.id === engineId)
  const needsCuda = engineInfo
    ? (engineInfo.requires_compute || []).includes('cuda')
    : engineId === 'stereo_sc_svd'
  let calibrated = false
  if (needsCuda) {
    return {
      proc_res: procRes, depth_model: depthModel, mode, inpaint_steps: 0, output,
      demo_seconds: 0, full_seconds: 0, vram_needed_gb: 16, status: 'no',
      notes: [`El motor ${engineInfo?.label || 'Calidad (inpainting SVD)'} requiere GPU NVIDIA con CUDA`],
      calibrated: false,
    }
  }

  const depthKey = `${kind}:depth:${depthModel}`
  let depthFps = cal[depthKey]
  if (depthFps === undefined) {
    depthFps = FALLBACK_DEPTH_FPS[kind][depthModel]
    if (kind === 'cpu') depthFps *= cpuScale
  } else { calibrated = true }

  // fps de la etapa estereo: warp clasico con su clave legacy; motores addon
  // con clave por id y semilla base_fps del manifest si no hay calibracion
  let warpFps: number
  if (engineId === 'stereo_fast') {
    const warpKey = `${kind}:warp:${procRes}`
    warpFps = cal[warpKey]
    if (warpFps === undefined) warpFps = FALLBACK_WARP_FPS[procRes] * cpuScale
    else calibrated = true
  } else {
    const engKey = `${kind}:stereo:${engineId}:${procRes}`
    warpFps = cal[engKey]
    if (warpFps === undefined) {
      const seed = engineInfo?.estimator?.base_fps?.[procRes]
      warpFps = (seed ?? FALLBACK_WARP_FPS[procRes] / 2) * cpuScale
      notes.push(`Motor ${engineInfo?.label || engineId} sin calibrar: estimación orientativa`)
    } else { calibrated = true }
  }

  const encKind = compute.amf ? 'amf' : 'x265'
  const encodeFps = cal[`${kind}:encode:${output}`]
    ?? FALLBACK_ENCODE_FPS[encKind][output] * (encKind === 'x265' ? cpuScale : 1.0)

  const tFrame = Math.max(1 / depthFps * 1.10, 1 / warpFps * 1.10, 1 / encodeFps)
  const totalFrames = durationS * fps
  const demoFrames = Math.min(demoDurationS, durationS) * fps
  const fullSeconds = SETUP_SECONDS + totalFrames * tFrame
  const demoSeconds = SETUP_SECONDS * 0.5 + demoFrames * tFrame

  const label = kind === 'dml' ? 'iGPU DirectML' : 'CPU'
  notes.unshift(`Sin CUDA: profundidad por frame (Depth Anything V2 ONNX, ${label}) + suavizado temporal — mucho más lento`)
  if (procRes === '4k') {
    notes.push('4K en este equipo es MUY lento; recomendado 1080p')
    if (compute.ram_gb && compute.ram_gb < 24) notes.push(`RAM (${compute.ram_gb.toFixed(0)} GB) justa para 4K`)
  }
  if (depthModel !== 'vda_s') notes.push('Base/Large por frame en este backend: horas extra y licencia CC-BY-NC')

  return {
    proc_res: procRes, depth_model: depthModel, mode, inpaint_steps: 0, output,
    demo_seconds: Math.round(demoSeconds), full_seconds: Math.round(fullSeconds),
    vram_needed_gb: 0.0, status: 'warn', notes, calibrated,
  }
}

export function estimateOne(durationS: number, fps: number, gpu: GpuInfo | null,
  procRes: string, depthModel: string, mode: string, inpaintSteps: number,
  output: string, demoDurationS = 60.0, compute: ComputeInfo | null = null,
  cal: Record<string, number> = {}, engines?: StereoEngineInfo[]): Estimate {
  const notes: string[] = []

  if (output === 'fsbs_4k' && procRes !== '4k') notes.push('Full-SBS 4K requiere procesar a 4K')
  if (output === 'hsbs_4k' && procRes === '1080p') notes.push('Salida 4K desde proceso 1080p: se reescala (calidad limitada)')
  if (output === 'fsbs_4k') notes.push('⚠ 7680×2160 excede el decodificador de las TV LG 3D (uso PC/VR)')

  if (gpu === null && compute !== null && (compute.kind === 'dml' || compute.kind === 'cpu')) {
    return estimateFallback(durationS, fps, compute, procRes, depthModel, mode, output, demoDurationS, cal, notes, engines)
  }

  const scaler = gpu && gpu.scaler ? gpu.scaler : UNKNOWN_SCALER
  const vram = gpu ? gpu.vram_gb : 0.0

  let calibrated = false
  const depthKey = `depth:${depthModel}:${procRes}`
  const depthBase = DEPTH_FPS[depthModel] * (procRes === '4k' ? DEPTH_4K_FACTOR : 1.0)
  const [depthFps, c1] = stageFps(depthKey, depthBase, scaler, cal)
  calibrated ||= c1

  const engineId = modeToEngine(mode)
  let stereoFps: number, c2: boolean
  if (engineId === 'stereo_fast') {
    [stereoFps, c2] = stageFps(`warp:${procRes}`, WARP_FPS[procRes], scaler, cal)
  } else if (engineId === 'stereo_sc_svd') {
    const base8 = HQ_INPAINT_FPS_8STEPS[procRes]
    const stepFactor = 0.35 + 0.65 * (inpaintSteps / 8.0)
    ;[stereoFps, c2] = stageFps(`inpaint:${procRes}:${inpaintSteps}`, base8 / stepFactor, scaler, cal)
  } else {
    // motor addon: clave de calibracion por id + semilla del manifest
    const engineInfo = engines?.find(e => e.id === engineId)
    const seed = engineInfo?.estimator?.base_fps?.[procRes] ?? WARP_FPS[procRes] / 2
    ;[stereoFps, c2] = stageFps(`stereo:${engineId}:${procRes}`, seed, scaler, cal)
    if (!c2) notes.push(`Motor ${engineInfo?.label || engineId} sin calibrar: estimación orientativa`)
  }
  calibrated ||= c2

  const [encodeFps] = stageFps(`encode:${output}`, ENCODE_FPS[output], 1.0, cal, false)

  let tFrame = Math.max(1 / depthFps, 1 / stereoFps, 1 / encodeFps, 1 / DECODE_FPS)
  tFrame /= OVERLAP_EFFICIENCY

  const totalFrames = durationS * fps
  const demoFrames = Math.min(demoDurationS, durationS) * fps
  let fullSeconds = SETUP_SECONDS + totalFrames * tFrame
  let demoSeconds = SETUP_SECONDS * 0.5 + demoFrames * tFrame

  const [vramNeeded, vstatus, vramNotes] = vramCheck(procRes, depthModel, mode, vram)
  let status: 'ok' | 'warn' | 'no' = vstatus
  notes.push(...vramNotes)
  if (gpu === null) {
    status = 'no'
    notes.push('Sin GPU NVIDIA detectada')
  } else if (status === 'warn') {
    const factor = mode === 'fast' ? 1.3 : 2.0
    fullSeconds *= factor
    demoSeconds *= factor
  }

  return {
    proc_res: procRes, depth_model: depthModel, mode,
    inpaint_steps: mode === 'hq' ? inpaintSteps : 0, output,
    demo_seconds: Math.round(demoSeconds), full_seconds: Math.round(fullSeconds),
    vram_needed_gb: vramNeeded, status, notes, calibrated,
  }
}

export function estimateMatrix(durationS: number, fps: number, gpu: GpuInfo | null,
  inpaintSteps = 8, demoDurationS = 60.0, compute: ComputeInfo | null = null,
  cal: Record<string, number> = {}, engines?: StereoEngineInfo[]): Estimate[] {
  // eje de modos = motores de estereo disponibles; sin lista (legacy o sin
  // worker), los dos clasicos de siempre -> matriz identica a la del port
  const modes = engines?.length ? engines.map(e => engineToMode(e.id)) : ['fast', 'hq']
  const rows: Estimate[] = []
  for (const procRes of ['1080p', '4k']) {
    for (const depthModel of DEPTH_ORDER) {
      for (const mode of modes) {
        for (const output of OUTPUT_ORDER) {
          if (output === 'fsbs_4k' && procRes !== '4k') continue
          rows.push(estimateOne(durationS, fps, gpu, procRes, depthModel, mode,
            inpaintSteps, output, demoDurationS, compute, cal, engines))
        }
      }
    }
  }
  return rows
}

function escapeRe(s: string): string { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
function round3(n: number): number { return Math.round(n * 1000) / 1000 }
