// Metadatos del fichero via ffprobe (portable). En SIMULATE devuelve ficticios.
import { basename } from 'pathe'
import { isSimulate } from './config'
import { execCapture } from './proc'

export interface ProbeResult {
  path: string
  filename: string
  duration_s: number
  video: { fps: number, hdr: boolean, width?: number, height?: number, codec?: string }
  audio_tracks: Array<Record<string, unknown>>
  subtitle_tracks: Array<Record<string, unknown>>
  chapters: number
}

function parseFps(v?: string): number {
  if (!v || v === '0/0') return 24
  if (v.includes('/')) {
    const [a, b] = v.split('/').map(Number)
    return b ? Math.round((a / b) * 1000) / 1000 : 24
  }
  return Number(v) || 24
}

function fakeProbe(path: string): ProbeResult {
  return {
    path, filename: basename(path), duration_s: 7200,
    video: { fps: 24, hdr: false, width: 3840, height: 2160, codec: 'hevc' },
    audio_tracks: [{ codec: 'eac3', language: 'spa' }],
    subtitle_tracks: [{ codec: 'subrip', language: 'spa' }],
    chapters: 0,
  }
}

export async function probeFile(path: string): Promise<ProbeResult> {
  if (isSimulate()) return fakeProbe(path)
  const r = await execCapture('ffprobe',
    ['-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', '-show_chapters', path],
    { timeoutMs: 30000 })
  let data: any = null
  if (r.ok) {
    try { data = JSON.parse(r.stdout) } catch { /* salida corrupta */ }
  }
  if (!data) {
    const detail = (r.stderr || 'ffprobe no disponible').slice(-300)
    throw createError({ statusCode: 400, statusMessage: `No se pudo analizar el fichero: ${detail}` })
  }
  const streams: any[] = data.streams || []
  const v = streams.find(s => s.codec_type === 'video')
  const audio = streams.filter(s => s.codec_type === 'audio')
    .map(s => ({ codec: s.codec_name, language: s.tags?.language, title: s.tags?.title }))
  const subs = streams.filter(s => s.codec_type === 'subtitle')
    .map(s => ({ codec: s.codec_name, language: s.tags?.language, title: s.tags?.title }))
  const transfer = v?.color_transfer || ''
  const hdr = transfer === 'smpte2084' || transfer === 'arib-std-b67'
  return {
    path, filename: basename(path),
    duration_s: Number(data.format?.duration) || 0,
    video: {
      fps: parseFps(v?.r_frame_rate || v?.avg_frame_rate),
      hdr, width: v?.width, height: v?.height, codec: v?.codec_name,
    },
    audio_tracks: audio,
    subtitle_tracks: subs,
    chapters: (data.chapters || []).length,
  }
}
