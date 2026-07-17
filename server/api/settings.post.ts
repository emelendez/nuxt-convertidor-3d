import { saveSettings } from '../utils/config'
import { assertLocal } from '../utils/security'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  // output_dir es la BASE de assertWithinOutputDir: si un remoto pudiera
  // cambiarla (p. ej. a C:\) el endpoint de descarga leeria todo el disco.
  if (body.output_dir != null) assertLocal(event)
  const patch: Record<string, string> = {}
  for (const k of ['output_dir', 'theme', 'language'] as const) {
    if (body[k] != null) patch[k] = String(body[k])
  }
  return { settings: await saveSettings(patch) }
})
