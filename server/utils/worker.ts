// Ejecucion de un job.
//  - SIMULATE: simulacion en Node (desarrollar UI/API sin GPU/FFmpeg).
//  - real: spawn del worker Python (worker/cli.py), un proceso por trabajo.
//    Contrato: el worker emite lineas JSON por stdout
//      {type:'progress',...} | {type:'done',output} | {type:'cancelled'} | {type:'error',message}
//    Node calcula el workdir (reanudacion) y se lo pasa; el worker no re-hashea.
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { createInterface } from 'node:readline'
import { basename, join } from 'pathe'
import { ROOT_DIR, outputDir } from './config'
import { OUTPUTS } from './estimator'
import { spawn } from './proc'
import { pythonExe, workerEnv } from './python'
import type { Job, JobProgress } from './jobs'

export async function runJob(
  job: Job,
  workdir: string,
  onProgress: (p: JobProgress) => void,
  signal: AbortSignal,
): Promise<string> {
  if (job.simulate) return runSimulated(job, onProgress, signal)
  return runReal(job, workdir, onProgress, signal)
}

// ── worker Python real ──────────────────────────────────────────────────────
function jobspec(job: Job, workdir: string) {
  return {
    job_id: job.id,
    source: job.source,
    probe: job.probe,
    cfg: job.cfg,
    segment_start: job.segment_start,
    segment_duration: job.segment_duration,
    is_demo: job.kind === 'demo',
    workdir,
    simulate: false,
  }
}

function runReal(
  job: Job,
  workdir: string,
  onProgress: (p: JobProgress) => void,
  signal: AbortSignal,
): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const py = pythonExe()
    const cli = join(ROOT_DIR, 'worker', 'cli.py')
    if (!existsSync(cli)) {
      return reject(new Error(`No se encontro el worker Python: ${cli}`))
    }
    mkdirSync(workdir, { recursive: true })
    const specPath = join(workdir, 'jobspec.json')
    writeFileSync(specPath, JSON.stringify(jobspec(job, workdir), null, 2), 'utf-8')

    const child = spawn(py, [cli, '--job', specPath], {
      cwd: ROOT_DIR,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: workerEnv(),
    })

    let output: string | null = null
    let failure: string | null = null
    let cancelled = false
    const stderrTail: string[] = []
    let killTimer: ReturnType<typeof setTimeout> | undefined

    // Cancelacion: pedir parada limpia por stdin y forzar kill si no cede.
    const onAbort = () => {
      try { child.stdin?.write('cancel\n') } catch { /* stdin ya cerrado */ }
      try { child.stdin?.end() } catch { /* idem */ }
      killTimer = setTimeout(() => { try { child.kill() } catch { /* ya muerto */ } }, 8000)
    }
    if (signal.aborted) onAbort()
    else signal.addEventListener('abort', onAbort, { once: true })

    // stdout: una linea JSON por evento.
    const rl = createInterface({ input: child.stdout! })
    rl.on('line', (line) => {
      const s = line.trim()
      if (!s) return
      let msg: any
      try { msg = JSON.parse(s) } catch { return }  // ruido no-JSON: ignorar
      if (msg.type === 'progress') {
        const { type, ...p } = msg
        onProgress(p as JobProgress)
      } else if (msg.type === 'done') {
        output = String(msg.output ?? '')
      } else if (msg.type === 'cancelled') {
        cancelled = true
      } else if (msg.type === 'error') {
        failure = String(msg.message ?? 'error desconocido del worker')
      }
    })

    // stderr: ruido de librerias; guardar la cola para diagnostico.
    const rlErr = createInterface({ input: child.stderr! })
    rlErr.on('line', (line) => {
      stderrTail.push(line)
      if (stderrTail.length > 40) stderrTail.shift()
    })

    child.on('error', (err) => {
      if (killTimer) clearTimeout(killTimer)
      reject(new Error(`No se pudo lanzar el worker Python (${py}): ${err.message}`))
    })

    child.on('close', (code) => {
      if (killTimer) clearTimeout(killTimer)
      signal.removeEventListener('abort', onAbort)
      if (cancelled || signal.aborted) return reject(new Error('cancelado'))
      if (failure) return reject(new Error(failure))
      if (output) return resolve(output)
      const tail = stderrTail.slice(-8).join('\n')
      reject(new Error(`El worker termino sin resultado (codigo ${code}).${tail ? '\n' + tail : ''}`))
    })
  })
}

// ── simulacion (Node) ────────────────────────────────────────────────────────
async function outputPath(job: Job): Promise<string> {
  const dir = await outputDir()
  mkdirSync(dir, { recursive: true })
  const stem = basename(job.source).replace(/\.[^.]+$/, '')
  const tag = String(OUTPUTS[job.cfg.output]?.label ?? job.cfg.output).replace(/ /g, '.')
  const kind = job.kind === 'demo' ? 'DEMO.' : ''
  return join(dir, `${stem}.${kind}3D.${tag}.mkv`)
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Error('cancelado'))
    const t = setTimeout(() => { signal.removeEventListener('abort', onAbort); resolve() }, ms)
    function onAbort() { clearTimeout(t); reject(new Error('cancelado')) }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

async function runSimulated(job: Job, onProgress: (p: JobProgress) => void, signal: AbortSignal): Promise<string> {
  const fps = job.probe?.video?.fps || 24
  const framesTotal = Math.max(1, Math.round(job.segment_duration * fps))
  const chunks = Math.max(1, Math.round(job.segment_duration / 10))
  const totalMs = 6000
  const steps = 40
  for (let i = 1; i <= steps; i++) {
    await sleep(totalMs / steps, signal)
    const frac = i / steps
    const done = i === steps
    onProgress({
      stage: done ? 'completado' : 'SIMULACIÓN: convirtiendo',
      frames_done: Math.round(framesTotal * frac),
      frames_total: framesTotal,
      fps: framesTotal / (totalMs / 1000),
      eta_s: Math.round((1 - frac) * (totalMs / 1000)),
      chunk: Math.min(chunks, Math.max(1, Math.ceil(frac * chunks))),
      chunks_total: chunks,
    })
  }
  const out = await outputPath(job)
  writeFileSync(out, `SIMULACIÓN — ${job.filename}\ncfg=${JSON.stringify(job.cfg)}\n`, 'utf-8')
  return out
}
