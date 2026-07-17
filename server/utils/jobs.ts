// Cola de jobs secuencial (una GPU) + eventos para SSE. Port de core/jobs.py
// al modelo del event loop de Node: cada job ejecuta un worker (subproceso Python
// en real, o simulacion en Node); sin hilos.
import { basename, join } from 'pathe'
import { jobsDir } from './config'
import { sha1Hex } from './hash'
import { runJob } from './worker'

export interface JobProgress {
  stage?: string
  frames_done?: number
  frames_total?: number
  fps?: number
  eta_s?: number
  chunk?: number
  chunks_total?: number
  thumbnail?: string
}

export interface Job {
  id: string
  kind: 'demo' | 'full'
  source: string
  filename: string
  cfg: Record<string, any>
  probe: Record<string, any>
  segment_start: number
  segment_duration: number
  state: 'queued' | 'running' | 'done' | 'error' | 'cancelled' | 'paused'
  created_at: number
  progress: JobProgress
  output: string | null
  error: string | null
  simulate: boolean
}

type Listener = (payload: string) => void

// Serializacion canonica y estable (claves ordenadas) para el hash del workdir.
function canonical(value: any): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  const keys = Object.keys(value).sort()
  return '{' + keys.map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}'
}

class JobManager {
  jobs = new Map<string, Job>()
  private queue: string[] = []
  private running = false
  private controllers = new Map<string, AbortController>()
  private listeners = new Set<Listener>()
  private eventId = 0

  submit(kind: 'demo' | 'full', source: string, cfg: Record<string, any>,
    probe: Record<string, any>, segmentStart: number, segmentDuration: number,
    simulate: boolean): Job {
    const id = crypto.randomUUID().replace(/-/g, '').slice(0, 12)
    const job: Job = {
      id, kind, source, filename: basename(source), cfg, probe,
      segment_start: segmentStart, segment_duration: segmentDuration,
      state: 'queued', created_at: Date.now() / 1000, progress: {},
      output: null, error: null, simulate,
    }
    this.jobs.set(id, job)
    this.controllers.set(id, new AbortController())
    this.queue.push(id)
    this.emit(job)
    void this.pump()
    return job
  }

  cancel(id: string): boolean {
    const job = this.jobs.get(id)
    if (!job) return false
    this.controllers.get(id)?.abort()
    if (job.state === 'queued') {
      job.state = 'cancelled'
      this.queue = this.queue.filter(x => x !== id)
      this.emit(job)
    }
    return true
  }

  listJobs(): Job[] {
    return [...this.jobs.values()].sort((a, b) => a.created_at - b.created_at)
  }

  // Directorio determinista por (fichero, cfg, kind, segmento) — reanudacion.
  // Calculo PURO (sin efectos): el mkdir lo hace worker.runReal justo antes de
  // escribir el jobspec; los lectores (preview) no necesitan crear nada.
  async workdirPath(job: Job): Promise<string> {
    const key = canonical([job.source, job.cfg, job.kind, job.segment_start, job.segment_duration])
    const digest = (await sha1Hex(key)).slice(0, 16)
    return join(jobsDir(), digest)
  }

  publicJob(job: Job): Omit<Job, 'probe'> {
    const { probe, ...pub } = job
    return pub
  }

  subscribe(cb: Listener): () => void {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  private emit(job: Job): void {
    this.eventId++
    const payload = JSON.stringify({ id: this.eventId, job: this.publicJob(job) })
    for (const cb of [...this.listeners]) {
      try { cb(payload) } catch { /* suscriptor caido */ }
    }
  }

  private async pump(): Promise<void> {
    if (this.running) return
    this.running = true
    try {
      while (this.queue.length) {
        const id = this.queue.shift()!
        const job = this.jobs.get(id)
        if (!job || job.state === 'cancelled') continue
        const ctrl = this.controllers.get(id)!
        job.state = 'running'
        this.emit(job)

        let last = 0
        const onProgress = (p: JobProgress) => {
          job.progress = { ...job.progress, ...p }
          const now = Date.now()
          if (now - last > 250 || p.stage === 'completado') { last = now; this.emit(job) }
        }

        try {
          const out = await runJob(job, await this.workdirPath(job), onProgress, ctrl.signal)
          if (ctrl.signal.aborted) job.state = 'cancelled'
          else { job.output = out; job.state = 'done' }
        } catch (e: any) {
          if (ctrl.signal.aborted) job.state = 'cancelled'
          else { job.state = 'error'; job.error = `${e?.name || 'Error'}: ${e?.message ?? e}` }
        }
        this.emit(job)
      }
    } finally {
      this.running = false
    }
  }
}

export const manager = new JobManager()
