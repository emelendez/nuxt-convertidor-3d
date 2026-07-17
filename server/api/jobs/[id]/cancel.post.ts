import { manager } from '../../../utils/jobs'

export default defineEventHandler((event) => {
  const id = getRouterParam(event, 'id')!
  if (!manager.cancel(id)) throw createError({ statusCode: 404, statusMessage: 'Trabajo no encontrado' })
  return { ok: true }
})
