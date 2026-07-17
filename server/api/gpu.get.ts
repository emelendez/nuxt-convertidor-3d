import { detectGpus } from '../utils/capabilities'

export default defineEventHandler(async () => {
  return { gpus: await detectGpus() }
})
