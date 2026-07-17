// Solo peticiones locales; validacion de rutas dentro de la carpeta de salida.
import { isAbsolute, relative, resolve } from 'pathe'
import type { H3Event } from 'h3'
import { outputDir } from './config'

export function isLocal(event: H3Event): boolean {
  const ip = getRequestIP(event, { xForwardedFor: false }) || ''
  return ip === '' || ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1'
}

export function assertLocal(event: H3Event): void {
  if (!isLocal(event)) {
    throw createError({ statusCode: 403, statusMessage: 'Solo disponible en local' })
  }
}

// ── Anti fuerza bruta del PIN (en memoria; se vacia al reiniciar) ───────────
const PIN_WINDOW_MS = 15 * 60 * 1000
const PIN_MAX_FAILS = 10
const pinFails = new Map<string, { count: number, since: number }>()

export function pinThrottled(ip: string): boolean {
  const e = pinFails.get(ip)
  if (!e) return false
  if (Date.now() - e.since > PIN_WINDOW_MS) { pinFails.delete(ip); return false }
  return e.count >= PIN_MAX_FAILS
}

export function notePinFailure(ip: string): void {
  const e = pinFails.get(ip)
  if (!e || Date.now() - e.since > PIN_WINDOW_MS) {
    pinFails.set(ip, { count: 1, since: Date.now() })
  } else {
    e.count++
  }
}

export function clearPinFailures(ip: string): void { pinFails.delete(ip) }

// Guarda anti path-traversal. ASSERT (lanza 400) y no predicado booleano a
// proposito: al ser async, un `if (!withinOutputDir(p))` con await olvidado
// compilaria y desactivaria la guarda en silencio (!Promise === false).
export async function assertWithinOutputDir(p: string,
  message = 'Fuera de la carpeta de salida'): Promise<void> {
  const base = resolve(await outputDir())
  const rel = relative(base, resolve(p))
  const ok = rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
  if (!ok) throw createError({ statusCode: 400, statusMessage: message })
}
