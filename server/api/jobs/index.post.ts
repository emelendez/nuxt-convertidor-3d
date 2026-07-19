import { isSimulate } from '../../utils/config'
import { getCapabilities } from '../../utils/capabilities'
import { manager } from '../../utils/jobs'
import { probeFile } from '../../utils/probe'
import { venvReady } from '../../utils/python'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  const kind = body.kind === 'demo' ? 'demo' : body.kind === 'full' ? 'full' : null
  if (!kind) throw createError({ statusCode: 400, statusMessage: 'kind debe ser demo o full' })
  if (!body.path) throw createError({ statusCode: 400, statusMessage: 'Falta la ruta del fichero' })

  // Pre-flight: sin worker Python instalado el spawn fallaria (ENOENT) de forma
  // ASINCRONA y el job quedaria en 'error' sin explicacion. Avisar aqui con un
  // 400 accionable ANTES de encolar. (En simulacion no hay worker real.)
  if (!isSimulate() && !venvReady()) {
    throw createError({ statusCode: 400, statusMessage: 'El worker de IA no está instalado. Instálalo con scripts\\setup.ps1 -Auto (auto-detecta tu hardware) y reinicia.' })
  }

  let info
  try {
    // await OBLIGATORIO: sin el, el catch del modo simulacion seria codigo muerto
    info = await probeFile(String(body.path))
  } catch (e: any) {
    if (isSimulate()) {
      info = { path: body.path, filename: String(body.path).split(/[\\/]/).pop(), duration_s: 7200,
        video: { fps: 24, hdr: false }, audio_tracks: [], subtitle_tracks: [], chapters: 0 }
    } else {
      throw e
    }
  }

  const duration = info.duration_s
  const required = ['proc_res', 'depth_model', 'mode', 'output']
  const cfgIn = body.cfg || {}
  const missing = required.filter(k => !(k in cfgIn))
  if (missing.length) throw createError({ statusCode: 400, statusMessage: `Config incompleta; faltan ${missing.join(', ')}` })
  const cfg = { divergence: 2.0, convergence: 0.5, inpaint_steps: 8, tonemap: true, ...cfgIn }

  // Motores RESUELTOS antes de encolar: cfg.engines entra en el hash del
  // workdir (jobs.ts), asi que 'auto' debe fijarse aqui a un motor concreto o
  // la reanudacion dependeria de que resolvio el worker en cada arranque.
  const caps = await getCapabilities()
  const engines = { ...(cfg.engines || {}) }
  if (!engines.stereo) engines.stereo = modeToEngine(cfg.mode)
  if (!engines.depth || engines.depth === 'auto') {
    engines.depth = caps.components.depth === 'vda' ? 'depth_vda' : 'depth_da2_onnx'
  }
  cfg.engines = engines
  cfg.mode = engineToMode(engines.stereo)   // coherencia legacy (worker/estimador)

  if (!isSimulate()) {
    // Gate generalizado: cada motor del cfg declara que computo exige
    for (const id of [engines.depth, engines.stereo]) {
      const eng = caps.engines?.find(e => e.id === id)
      const needs = eng ? eng.requires_compute : (id === 'stereo_sc_svd' || id === 'depth_vda' ? ['cuda'] : [])
      if (needs.includes('cuda') && caps.compute.kind !== 'cuda') {
        throw createError({ statusCode: 400, statusMessage: `El motor ${eng?.label || id} requiere GPU NVIDIA con CUDA; elige otro motor` })
      }
      if (eng && !eng.available) {
        throw createError({ statusCode: 400, statusMessage: `Motor ${eng.label} no disponible: ${eng.missing.join('; ') || 'componentes ausentes'}` })
      }
    }
  }

  let segStart: number, segDur: number
  if (kind === 'demo') {
    const dur = Math.min(Math.max(Number(body.demo_duration_s) || 60, 10), 300)
    const mode = body.demo_start_mode || 'fixed'
    if (mode === 'middle') segStart = Math.max(duration / 2 - dur / 2, 0)
    else if (mode === 'custom') segStart = Math.min(Math.max(Number(body.demo_start_s) || 0, 0), Math.max(duration - dur, 0))
    else segStart = Math.min(600, duration * 0.25)
    segDur = Math.min(dur, duration - segStart)
  } else {
    segStart = 0
    segDur = duration
  }

  const job = manager.submit(kind, info.path, cfg, info, segStart, segDur, isSimulate())
  return { job: manager.publicJob(job) }
})
