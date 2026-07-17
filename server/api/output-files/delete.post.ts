import { unlink } from 'node:fs/promises'
import { fileSize } from '../../utils/fileActions'
import { assertWithinOutputDir } from '../../utils/security'

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  const p = String(body.path || '')
  await assertWithinOutputDir(p, 'Solo se pueden borrar ficheros de la carpeta de salida')
  if (await fileSize(p) === null) throw createError({ statusCode: 404, statusMessage: 'Fichero no encontrado' })
  try { await unlink(p) } catch (e: any) { throw createError({ statusCode: 500, statusMessage: `No se pudo borrar: ${e.message}` }) }
  return { ok: true }
})
