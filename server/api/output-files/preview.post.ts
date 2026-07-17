import { join } from 'pathe'
import { ensurePreviewsDir, fileSize, makeOutputPreview, previewCacheName } from '../../utils/fileActions'
import { assertWithinOutputDir } from '../../utils/security'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  const p = String(body.path || '')
  await assertWithinOutputDir(p)
  if (await fileSize(p) === null) throw createError({ statusCode: 404, statusMessage: 'Fichero no encontrado' })
  const name = await previewCacheName(p)
  const out = join(ensurePreviewsDir(), name)
  if (await fileSize(out) === null) {
    try { await makeOutputPreview(p, out) }
    catch (e: any) { throw createError({ statusCode: 500, statusMessage: e.message }) }
  }
  return { name }
})
