// Descarga de un MKV convertido (demo o completa). Pensado para clientes en
// red: streaming puro con soporte Range/206 (reanudable con gestores de
// descargas). El acceso remoto lo gobierna el middleware de PIN, no assertLocal.
import { stat } from 'node:fs/promises'
import { basename } from 'pathe'
import { parseByteRange, streamFile } from '../../utils/fileActions'
import { assertWithinOutputDir } from '../../utils/security'

export default defineEventHandler(async (event) => {
  const p = String(getQuery(event).path || '')
  if (!p) throw createError({ statusCode: 400, statusMessage: 'Falta el parámetro path' })
  if (!p.toLowerCase().endsWith('.mkv')) {
    throw createError({ statusCode: 400, statusMessage: 'Solo se descargan ficheros .mkv' })
  }
  await assertWithinOutputDir(p, 'Solo se pueden descargar ficheros de la carpeta de salida')
  const st = await stat(p).catch(() => null)
  if (!st?.isFile()) throw createError({ statusCode: 404, statusMessage: 'Fichero no encontrado' })

  // filename= solo ASCII imprimible sin comillas/backslash (sin CR/LF -> sin
  // header injection); filename* conserva el nombre real en UTF-8.
  const name = basename(p)
  const ascii = name.replace(/[^\x20-\x7E]/g, '_').replace(/["\\]/g, '_')
  setHeader(event, 'Content-Type', 'video/x-matroska')
  setHeader(event, 'Accept-Ranges', 'bytes')
  setHeader(event, 'Content-Disposition',
    `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(name)}`)

  const range = parseByteRange(getRequestHeader(event, 'range'), st.size)
  if (range === 'unsatisfiable') {
    setResponseStatus(event, 416)
    setHeader(event, 'Content-Range', `bytes */${st.size}`)
    return ''
  }
  if (range) {
    setResponseStatus(event, 206)
    setHeader(event, 'Content-Range', `bytes ${range.start}-${range.end}/${st.size}`)
    setHeader(event, 'Content-Length', String(range.end - range.start + 1))
    return streamFile(p, range)
  }
  setHeader(event, 'Content-Length', String(st.size))
  return streamFile(p)
})
