// Control de acceso remoto por PIN — FAIL-CLOSED.
// Local (127.0.0.1/::1) pasa siempre sin peaje. Remoto: sin PIN configurado
// en el servidor no entra NADIE; con PIN, `?pin=` una vez → cookie HttpOnly
// (guarda el SHA-256, nunca el PIN) → SSE, <video> y <a download> funcionan
// solos porque las cookies same-origin viajan automaticamente.
// El middleware solo lanza errores o redirige; el formulario vive en /pin.
import { remotePin } from '../utils/config'
import { sha256Hex } from '../utils/hash'
import { clearPinFailures, isLocal, notePinFailure, pinThrottled } from '../utils/security'

const COOKIE = 'c3d_auth'

// Cachea el hash del PIN por proceso (se recalcula si el PIN cambia).
let cached: { pin: string, hash: string } | null = null
async function pinHash(pin: string): Promise<string> {
  if (cached?.pin !== pin) cached = { pin, hash: await sha256Hex(pin) }
  return cached.hash
}

export default defineEventHandler(async (event) => {
  if (isLocal(event)) return

  const pin = remotePin()
  if (!pin) {
    throw createError({ statusCode: 403, statusMessage: 'Acceso remoto deshabilitado (servidor sin PIN)' })
  }
  if (event.path === '/pin' || event.path.startsWith('/pin?')) return

  const expected = await pinHash(pin)
  if (getCookie(event, COOKIE) === expected) return

  const ip = getRequestIP(event, { xForwardedFor: false }) || '?'
  if (pinThrottled(ip)) {
    throw createError({ statusCode: 429, statusMessage: 'Demasiados intentos; espera 15 minutos' })
  }
  const q = getQuery(event).pin
  if (typeof q === 'string' && q) {
    if (await sha256Hex(q) === expected) {
      clearPinFailures(ip)
      setCookie(event, COOKIE, expected, {
        httpOnly: true, sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 30,
      })
      // Redirigir sin ?pin= para que no se quede en la barra de direcciones
      if (!event.path.startsWith('/api/')) {
        return sendRedirect(event, event.path.split('?')[0] || '/', 302)
      }
      return
    }
    notePinFailure(ip)
  }
  if (event.path.startsWith('/api/')) {
    throw createError({ statusCode: 401, statusMessage: 'PIN requerido' })
  }
  return sendRedirect(event, '/pin', 302)
})
