import { join } from 'pathe'
import { previewsDir } from '../../../utils/config'
import { fileSize, streamFile } from '../../../utils/fileActions'

export default defineEventHandler(async (event) => {
  const name = getRouterParam(event, 'name') || ''
  if (!/^[0-9a-f]{8,40}\.mp4$/.test(name)) throw createError({ statusCode: 400, statusMessage: 'Nombre inválido' })
  const p = join(previewsDir(), name)
  const size = await fileSize(p)
  if (size === null) throw createError({ statusCode: 404, statusMessage: 'Previsualización no disponible' })
  setHeader(event, 'Content-Type', 'video/mp4')
  setHeader(event, 'Content-Length', String(size))
  return streamFile(p)
})
