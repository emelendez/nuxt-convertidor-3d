import { getCapabilities } from '../utils/capabilities'
import { DEPTH_MODELS, OUTPUTS, estimateMatrix, loadCalibration } from '../utils/estimator'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  // calibracion cargada UNA vez por peticion y pasada a la matriz (42 celdas)
  const [cap, cal] = await Promise.all([getCapabilities(), loadCalibration()])
  const idx = body.gpu_index ?? 0
  const gpu = cap.gpus[idx] ?? cap.gpus[0] ?? null
  const rows = estimateMatrix(
    Number(body.duration_s) || 0,
    Number(body.fps) || 24,
    gpu,
    Number(body.inpaint_steps) || 8,
    Number(body.demo_duration_s) || 60,
    cap.compute,
    cal,
  )
  return {
    gpu,
    compute: cap.compute,
    rows,
    outputs: OUTPUTS,
    depth_models: DEPTH_MODELS,
    calibration: cal,
  }
})
