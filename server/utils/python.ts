// Helpers compartidos para invocar el worker Python (cli.py, detect.py).
import { existsSync } from 'node:fs'
import { join } from 'pathe'
import { ROOT_DIR, dataDir, isSimulate, modelsDir, pythonOverride } from './config'

function venvPython(): string {
  return process.platform === 'win32'
    ? join(ROOT_DIR, '.venv', 'Scripts', 'python.exe')
    : join(ROOT_DIR, '.venv', 'bin', 'python')
}

// Interprete del worker: override por configuracion, si no el venv del proyecto,
// si no el `python` del PATH (ultimo recurso).
export function pythonExe(): string {
  const override = pythonOverride()
  if (override) return override
  const venv = venvPython()
  return existsSync(venv) ? venv : 'python'
}

// True si hay un interprete del worker instalado (venv u override explicito).
export function venvReady(): boolean {
  return !!pythonOverride() || existsSync(venvPython())
}

// Entorno para el subproceso: comparte data/ y models/ con Node y fuerza UTF-8.
// El worker Python usa SIEMPRE los nombres CONVERTIDOR3D_* (contrato propio de
// worker/backend/config.py, independiente de como se configure Node).
export function workerEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    CONVERTIDOR3D_DATA: dataDir(),
    CONVERTIDOR3D_MODELS: modelsDir(),
    CONVERTIDOR3D_SIMULATE: isSimulate() ? '1' : '0',
    PYTHONUNBUFFERED: '1',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  }
}
