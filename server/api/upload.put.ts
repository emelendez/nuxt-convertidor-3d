// Subida de una pelicula desde el dispositivo del cliente (remoto). Streaming
// directo del body a disco — NUNCA multipart en memoria: son ficheros de GB.
// El cliente envia el File como body (XHR PUT) y el nombre por query.
import { existsSync } from 'node:fs'
import { unlink } from 'node:fs/promises'
import { basename, extname, join } from 'pathe'
import { uploadsDir } from '../utils/config'
import { ensureDir, writeStreamToFile } from '../utils/fileActions'

const VIDEO_EXTS = new Set(['.mkv', '.mp4', '.m4v', '.mov', '.ts', '.m2ts'])

export default defineEventHandler(async (event) => {
  // basename + saneado: el nombre viene del cliente, jamas puede salir del dir
  const raw = basename(String(getQuery(event).name || ''))
  const name = raw.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_').trim()
  const ext = extname(name).toLowerCase()
  if (!name || !VIDEO_EXTS.has(ext)) {
    throw createError({ statusCode: 400, statusMessage: 'Nombre o extensión de vídeo no válidos' })
  }
  const dir = ensureDir(uploadsDir())
  const stem = name.slice(0, name.length - ext.length)
  let out = join(dir, name)
  for (let i = 1; existsSync(out); i++) out = join(dir, `${stem}-${i}${ext}`)

  try {
    await writeStreamToFile(event.node.req, out)
  } catch (e: any) {
    await unlink(out).catch(() => {}) // no dejar restos a medias
    throw createError({ statusCode: 500, statusMessage: `La subida falló: ${e?.message || e}` })
  }
  return { path: out, name: basename(out) }
})
