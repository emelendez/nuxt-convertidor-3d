// Helpers compartidos para invocar el worker Python (cli.py, detect.py).
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'pathe'
import { ROOT_DIR, dataDir, isSimulate, modelsDir, pythonOverride } from './config'

function venvPython(base: string): string {
  return process.platform === 'win32'
    ? join(base, 'Scripts', 'python.exe')
    : join(base, 'bin', 'python')
}

// Interprete del worker: override por configuracion, si no el venv del proyecto,
// si no el `python` del PATH (ultimo recurso).
export function pythonExe(): string {
  const override = pythonOverride()
  if (override) return override
  const venv = venvPython(join(ROOT_DIR, '.venv'))
  return existsSync(venv) ? venv : 'python'
}

// Interprete para UN job segun sus motores: si algun motor del cfg declara
// "venv": "isolated" en su manifest Y existe .venv-engines/<id>, se usa ese
// venv (deps irreconciliables con la pila compartida); si no, el interprete
// normal. Cada job es un spawn, asi que elegir interprete por job es gratis.
export function pythonExeForEngines(engineIds: string[]): string {
  for (const id of engineIds) {
    if (!id) continue
    try {
      const mpath = join(ROOT_DIR, 'worker', 'engines', id, 'manifest.json')
      if (!existsSync(mpath)) continue
      const manifest = JSON.parse(readFileSync(mpath, 'utf-8'))
      if (manifest?.venv === 'isolated') {
        const iso = venvPython(join(ROOT_DIR, '.venv-engines', id))
        if (existsSync(iso)) return iso
      }
    } catch { /* manifest ilegible: interprete normal */ }
  }
  return pythonExe()
}

// True si hay un interprete del worker instalado (venv u override explicito).
export function venvReady(): boolean {
  return !!pythonOverride() || existsSync(venvPython(join(ROOT_DIR, '.venv')))
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
