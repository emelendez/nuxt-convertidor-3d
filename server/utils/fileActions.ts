// Acciones sobre ficheros de salida: abrir carpeta, borrar, clip de preview H264.
// Port de las utilidades de backend/api/routes.py + encode.make_output_preview.
import { createReadStream, createWriteStream, mkdirSync } from 'node:fs'
import { stat } from 'node:fs/promises'
import { Readable } from 'node:stream'
import { previewsDir } from './config'
import { sha1Hex } from './hash'
import { execCapture, spawnDetached } from './proc'

// ── adapter de ficheros (node:fs confinado aqui) ────────────────────────────

// Tamanyo en bytes, o null si no existe/no es accesible.
export async function fileSize(p: string): Promise<number | null> {
  try {
    const st = await stat(p)
    return st.isFile() ? st.size : null
  } catch { return null }
}

// Streaming como ReadableStream web: los handlers lo DEVUELVEN directamente
// (h3 1.15 lo soporta y lo recomienda; sendStream desaparece en h3 v2).
// opts {start,end} (inclusivos) casan con createReadStream y con Range HTTP.
export function streamFile(p: string, opts?: { start?: number, end?: number }): ReadableStream {
  return Readable.toWeb(createReadStream(p, opts)) as unknown as ReadableStream
}

// Parser de la cabecera Range (RFC 7233, unidad bytes). Devuelve:
//  {start,end} inclusivos → responder 206; 'unsatisfiable' → 416;
//  null → sin Range valido o multi-range → responder 200 completo (permitido).
export function parseByteRange(header: string | undefined, size: number):
  { start: number, end: number } | 'unsatisfiable' | null {
  if (!header || size <= 0) return null
  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim())
  if (!m) return null // sintaxis rara o multi-range ("a-b,c-d"): servir completo
  const [, a, b] = m
  if (a === '' && b === '') return null
  let start: number, end: number
  if (a === '') { // sufijo "-n": ultimos n bytes
    const n = Number(b)
    if (n === 0) return 'unsatisfiable'
    start = Math.max(size - n, 0)
    end = size - 1
  } else {
    start = Number(a)
    end = b === '' ? size - 1 : Math.min(Number(b), size - 1)
  }
  if (start >= size || start > end) return 'unsatisfiable'
  return { start, end }
}

export function ensureDir(p: string): string {
  mkdirSync(p, { recursive: true })
  return p
}

// Vuelca un stream legible Node (p. ej. el body de una peticion) a un fichero.
export function writeStreamToFile(source: NodeJS.ReadableStream, out: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = createWriteStream(out)
    source.pipe(ws)
    ws.on('finish', () => resolve())
    ws.on('error', reject)
    source.on('error', reject)
  })
}

export function openInSystem(p: string): void {
  if (process.platform === 'win32') {
    // 'start' necesita shell; el primer arg vacio es el titulo de ventana.
    spawnDetached('cmd', ['/c', 'start', '', p])
  } else if (process.platform === 'darwin') {
    spawnDetached('open', [p])
  } else {
    spawnDetached('xdg-open', [p])
  }
}

export async function previewCacheName(src: string): Promise<string> {
  const st = await stat(src)
  const key = `${src}|${st.mtimeMs}|${st.size}|v1`
  return (await sha1Hex(key)).slice(0, 16) + '.mp4'
}

async function ffprobeDuration(src: string): Promise<number | null> {
  const r = await execCapture('ffprobe',
    ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', src],
    { timeoutMs: 30000 })
  if (!r.ok) return null
  const d = Number(r.stdout.trim())
  return Number.isFinite(d) ? d : null
}

// Clip corto H.264 (mantiene el layout SBS) para previsualizar en el navegador
// un fichero de salida HEVC. Equivale a encode.make_output_preview.
export async function makeOutputPreview(src: string, out: string, clipS = 45): Promise<void> {
  const dur = await ffprobeDuration(src)
  let start = 0
  if (dur && dur > clipS + 5) start = Math.min(dur * 0.15, Math.max(dur - clipS, 0))
  // -nostdin: execFile deja el stdin del hijo como pipe abierto y ffmpeg
  // puede bloquearse leyendolo (deadlock cazado en el mux del worker).
  const args = ['-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
  if (start > 0) args.push('-ss', start.toFixed(2))
  args.push('-i', src, '-t', String(clipS),
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
    '-pix_fmt', 'yuv420p', '-vf', 'scale=-2:1080',
    '-an', '-movflags', '+faststart', out)
  const r = await execCapture('ffmpeg', args, { timeoutMs: 1800000 })
  if (!r.ok) throw new Error(`Preview falló: ${r.stderr.slice(-400)}`)
}

export function ensurePreviewsDir(): string {
  const d = previewsDir()
  mkdirSync(d, { recursive: true })
  return d
}
