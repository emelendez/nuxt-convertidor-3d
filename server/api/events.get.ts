// SSE de eventos de jobs (equivale a GET /api/events del backend Python).
import { manager } from '../utils/jobs'

export default defineEventHandler(async (event) => {
  const stream = createEventStream(event)

  // h3 no vuelca las cabeceras hasta el primer push: sin este saludo, con la
  // cola vacia el EventSource se queda "conectando" hasta el primer keepalive
  // (15 s). El cliente ignora los eventos que no escucha.
  stream.push({ event: 'hello', data: '1' }).catch(() => {})

  // Estado actual al conectar (cubre reconexiones).
  for (const job of manager.listJobs()) {
    stream.push({ event: 'job', data: JSON.stringify({ job: manager.publicJob(job) }) }).catch(() => {})
  }

  const unsub = manager.subscribe((payload) => {
    stream.push({ event: 'job', data: payload }).catch(() => {})
  })
  const keepalive = setInterval(() => {
    stream.push({ event: 'keepalive', data: '1' }).catch(() => {})
  }, 15000)

  stream.onClosed(() => {
    clearInterval(keepalive)
    unsub()
  })

  return stream.send()
})
