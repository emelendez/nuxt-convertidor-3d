import { probeFile } from '../utils/probe'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  if (!body.path) throw createError({ statusCode: 400, statusMessage: 'Falta la ruta del fichero' })
  return await probeFile(String(body.path))
})
