// THIN ADAPTER de procesos — unico modulo del server que importa
// node:child_process (no hay equivalente web-platform para spawnear procesos;
// el resto del codigo consume esta superficie pequenya y async).
//
// Todo es async a proposito: las variantes sincronas (execFileSync) bloqueaban
// el event loop entero (server monohilo) hasta 10-30 s por peticion.
import { execFile, spawn } from 'node:child_process'

export interface ExecResult {
  ok: boolean
  code: number | null
  stdout: string
  stderr: string
}

export interface ExecOptions {
  timeoutMs?: number
  env?: NodeJS.ProcessEnv
  cwd?: string
  maxBuffer?: number
}

// Ejecuta y captura stdout/stderr. Nunca lanza: ok=false con el detalle en stderr.
export function execCapture(cmd: string, args: string[], opts: ExecOptions = {}): Promise<ExecResult> {
  return new Promise((resolve) => {
    execFile(cmd, args, {
      timeout: opts.timeoutMs ?? 30000,
      env: opts.env,
      cwd: opts.cwd,
      maxBuffer: opts.maxBuffer ?? 32 * 1024 * 1024,
      encoding: 'utf-8',
    }, (error: any, stdout, stderr) => {
      resolve({
        ok: !error,
        code: error ? (typeof error.code === 'number' ? error.code : null) : 0,
        stdout: String(stdout ?? ''),
        stderr: String(stderr ?? '') || String(error?.message ?? ''),
      })
    })
  })
}

// True si `cmd` existe en el PATH.
export async function which(cmd: string): Promise<boolean> {
  const finder = process.platform === 'win32' ? 'where' : 'which'
  return (await execCapture(finder, [cmd], { timeoutMs: 10000 })).ok
}

// Proceso desacoplado y sin esperar (abrir carpeta/fichero con la app del sistema).
export function spawnDetached(cmd: string, args: string[]): void {
  spawn(cmd, args, { detached: true, stdio: 'ignore' }).unref()
}

// Spawn con pipes para procesos largos con streaming (worker Python).
export { spawn }
