import { join } from 'pathe'
import { fileSize, streamFile } from '../../../utils/fileActions'
import { manager } from '../../../utils/jobs'

export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id')!
  const codec = String(getQuery(event).codec || 'h264')
  const job = manager.jobs.get(id)
  if (!job) throw createError({ statusCode: 404, statusMessage: 'Trabajo no encontrado' })
  const name = codec === 'hevc' ? 'preview.mp4' : 'preview_h264.mp4'
  const p = join(await manager.workdirPath(job), name)
  const size = await fileSize(p)
  if (size === null) throw createError({ statusCode: 404, statusMessage: 'Preview no disponible' })
  setHeader(event, 'Content-Type', 'video/mp4')
  setHeader(event, 'Content-Length', String(size))
  return streamFile(p)
})
