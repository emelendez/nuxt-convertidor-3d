import { isSimulate } from '../../utils/config'
import { getCapabilities } from '../../utils/capabilities'
import { manager } from '../../utils/jobs'
import { probeFile } from '../../utils/probe'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  const kind = body.kind === 'demo' ? 'demo' : body.kind === 'full' ? 'full' : null
  if (!kind) throw createError({ statusCode: 400, statusMessage: 'kind debe ser demo o full' })
  if (!body.path) throw createError({ statusCode: 400, statusMessage: 'Falta la ruta del fichero' })

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

  if (cfg.mode === 'hq' && !isSimulate()) {
    const { compute } = await getCapabilities()
    if (compute.kind !== 'cuda') {
      throw createError({ statusCode: 400, statusMessage: 'El modo Calidad (inpainting SVD) requiere GPU NVIDIA con CUDA; usa el modo Rápido' })
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
