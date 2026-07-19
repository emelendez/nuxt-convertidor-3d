// Miniaturas del vídeo de ORIGEN para el selector de inicio de la demo: extrae
// un fotograma JPEG por cada timestamp pedido y los devuelve en base64.
// Es la contraparte de servidor del cliente api.thumbnails() (useApi.ts) y
// espeja el contrato del worker Python (POST /thumbnails).
//
// Seguridad: lee un frame de un vídeo del disco del servidor. Coherente con el
// modelo ya aceptado — un cliente remoto con PIN ya puede listar el disco
// (GET /api/fs/list) y convertir cualquier vídeo. La guarda ext-vídeo +
// existencia lo acota a lo mismo; no requiere assertLocal.
import { extname } from 'pathe'
import { extractThumbnail, fileSize } from '../utils/fileActions'

// Mismo allowlist que server/api/fs/list.get.ts y upload.put.ts.
const VIDEO_EXTS = new Set(['.mkv', '.mp4', '.m4v', '.mov', '.ts', '.m2ts'])

// Extracciones ffmpeg concurrentes como maximo. Lanzar las N a la vez satura
// la CPU (decodificar un frame de 4K HEVC HDR obliga a decodificar todo su GOP)
// y algunas superan el timeout -> miniaturas nulas intermitentes. Un pool
// pequenyo mantiene la extraccion fiable.
const THUMB_CONCURRENCY = 3

// map con limite de concurrencia, preservando el orden de los resultados.
async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T, i: number) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length)
  let next = 0
  async function worker() {
    while (next < items.length) {
      const i = next++
      results[i] = await fn(items[i]!, i)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

export default defineEventHandler(async (event) => {
  const body = await readBody(event) || {}
  const path = String(body.path || '')
  if (!path) throw createError({ statusCode: 400, statusMessage: 'Falta la ruta del vídeo' })
  if (!VIDEO_EXTS.has(extname(path).toLowerCase())) {
    throw createError({ statusCode: 400, statusMessage: 'La ruta no es un vídeo' })
  }
  if (await fileSize(path) === null) {
    throw createError({ statusCode: 404, statusMessage: 'Fichero no encontrado' })
  }
  // Máx. 12 timestamps (igual que el worker); saneados a números finitos >= 0.
  const timestamps = (Array.isArray(body.timestamps) ? body.timestamps : [])
    .map(Number).filter((n: number) => Number.isFinite(n)).slice(0, 12)

  const thumbnails = await mapLimit(timestamps, THUMB_CONCURRENCY, async (t: number) => {
    const buf = await extractThumbnail(path, t)
    return buf ? buf.toString('base64') : null
  })
  return { thumbnails }
})
