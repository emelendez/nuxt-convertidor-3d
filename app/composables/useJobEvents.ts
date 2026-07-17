// Suscripcion SSE a eventos de jobs + polling de output-files (equivale a sse.js).
import { useAppStore } from '~/stores/app'

export function useJobEvents() {
  const store = useAppStore()
  const api = useApi()
  let es: EventSource | null = null
  let poll: ReturnType<typeof setInterval> | null = null

  function start() {
    if (import.meta.server || es) return
    es = new EventSource('/api/events')
    es.addEventListener('job', (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data)
        store.upsertJob(data.job || data)
      } catch { /* evento malformado */ }
    })
    const refresh = () => api.getOutputFiles(50).then(f => store.setOutputFiles(f)).catch(() => {})
    refresh()
    poll = setInterval(refresh, 5000)
  }

  function stop() {
    es?.close(); es = null
    if (poll) { clearInterval(poll); poll = null }
  }

  onMounted(start)
  onUnmounted(stop)
  return { start, stop }
}
