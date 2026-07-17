// Formateadores portados de frontend/src/ui.js (auto-importados por Nuxt).

export function fmtBytes(b?: number): string {
  if (!b) return '—'
  const gb = b / 2 ** 30
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(b / 2 ** 20).toFixed(0)} MB`
}

export function fmtDuration(s?: number | null): string {
  if (s == null || !isFinite(s)) return '—'
  s = Math.round(s)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 48) return `~${(h / 24).toFixed(1)} días`
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`
  if (m > 0) return `${m} min ${String(sec).padStart(2, '0')} s`
  return `${sec} s`
}

export function fmtTimestamp(s: number): string {
  s = Math.max(0, Math.round(s))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

export function parseTimestamp(str: string): number | null {
  const parts = String(str).trim().split(':').map(Number)
  if (parts.some(n => Number.isNaN(n))) return null
  return parts.reverse().reduce((acc, v, i) => acc + v * 60 ** i, 0)
}
