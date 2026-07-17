// Configuracion global del servidor — THIN ADAPTER de entorno.
// Unico modulo que consulta configuracion de entorno. Prioridad:
//   1. useRuntimeConfig().convertidor3d  (idiomatico Nuxt; override en runtime
//      con NUXT_CONVERTIDOR3D_SIMULATE / _DATA_DIR / _MODELS_DIR / _PYTHON_EXE)
//   2. variables legacy CONVERTIDOR3D_*  (compatibilidad: scripts, docs, habitos)
//   3. defaults calculados EN RUNTIME (app portable: jamas hornear rutas en build)
import { join, resolve } from 'pathe'
import { mkdirSync } from 'node:fs'

export const APP_NAME = 'Convertidor 3D'
export const APP_VERSION = '0.1.0'

// Raiz del proyecto (donde viven worker/, .venv, tools/, models/, data/).
// process.cwd() en runtime: run.bat/start.ps1 arrancan desde la raiz.
export const ROOT_DIR = process.cwd()

// Almacen INTERNO de conversiones, relativo al proyecto (viaja con la carpeta;
// gitignored). La app gestiona su ciclo de vida desde la UI (previsualizar /
// borrar; futuro boton "Descargar"). Configurable en data/settings.json
// (output_dir) si se prefiere un disco de medios (p. ej. D:\PELICULAS\3D).
export const DEFAULT_OUTPUT_DIR = 'data/conversions'

interface AppRuntimeConfig {
  simulate?: unknown
  dataDir?: unknown
  modelsDir?: unknown
  pythonExe?: unknown
  pin?: unknown
}

function rc(): AppRuntimeConfig {
  try {
    return ((useRuntimeConfig().convertidor3d as AppRuntimeConfig) ?? {})
  } catch {
    return {} // fuera del contexto Nitro (tests, scripts)
  }
}

function rcStr(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

// Modo simulacion: pipeline falso para desarrollar la UI sin GPU/FFmpeg.
// Ojo: los overrides de env pasan por destr ('true' -> boolean, '1' -> numero).
export function isSimulate(): boolean {
  const v = rc().simulate
  if (v === true || v === 1 || v === '1' || v === 'true') return true
  return process.env.CONVERTIDOR3D_SIMULATE === '1'
}

// Modelos y datos pueden vivir en otro disco (o apuntar al proyecto Python
// original en solo lectura).
export function modelsDir(): string {
  return rcStr(rc().modelsDir) || process.env.CONVERTIDOR3D_MODELS || join(ROOT_DIR, 'models')
}

export function dataDir(): string {
  return rcStr(rc().dataDir) || process.env.CONVERTIDOR3D_DATA || join(ROOT_DIR, 'data')
}

export function jobsDir(): string { return join(dataDir(), 'jobs') }
export function previewsDir(): string { return join(dataDir(), 'previews') }
// Peliculas subidas desde dispositivos remotos (no se auto-borran tras convertir)
export function uploadsDir(): string { return join(dataDir(), 'uploads') }

// Interprete Python del worker (override explicito; si no, .venv del proyecto).
export function pythonOverride(): string {
  return rcStr(rc().pythonExe) || process.env.CONVERTIDOR3D_PYTHON || ''
}

// Puerto real de escucha (lo fija start.ps1 via NITRO_PORT/PORT).
export function listenPort(): number {
  return Number(process.env.NITRO_PORT || process.env.PORT) || 8765
}

// PIN de acceso remoto. Vacio = solo clientes locales (fail-closed).
export function remotePin(): string {
  const v = rc().pin
  // destr puede convertir un PIN numerico ('12345678') en number
  return (typeof v === 'string' || typeof v === 'number') && String(v)
    ? String(v)
    : process.env.CONVERTIDOR3D_PIN || ''
}

export interface Settings {
  output_dir: string
  language: string
  theme: string
}

function defaultSettings(): Settings {
  return { output_dir: DEFAULT_OUTPUT_DIR, language: 'es', theme: 'auto' }
}

// Settings via useStorage('appdata') — montado en bootstrap.ts sobre dataDir().
// En disco sigue siendo data/settings.json en JSON plano: lo leen tambien el
// worker Python (config.py) y los humanos.
export async function loadSettings(): Promise<Settings> {
  try {
    const raw = await useStorage('appdata').getItem<Partial<Settings>>('settings.json')
    if (raw && typeof raw === 'object') return { ...defaultSettings(), ...raw }
  } catch { /* ilegible: usar defaults */ }
  return defaultSettings()
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  const merged = { ...(await loadSettings()), ...patch }
  // setItemRaw: escribe el string tal cual -> conserva el pretty-print
  await useStorage('appdata').setItemRaw('settings.json', JSON.stringify(merged, null, 2))
  return merged
}

export async function outputDir(): Promise<string> {
  const raw = (await loadSettings()).output_dir || DEFAULT_OUTPUT_DIR
  // SIEMPRE absoluta, resuelta contra la raiz del proyecto: cubre el default
  // relativo y cualquier valor del usuario (las absolutas quedan intactas).
  // El worker Python resuelve su copia contra su cwd = ROOT_DIR (worker.ts).
  return resolve(ROOT_DIR, raw)
}

export function ensureDirs(): void {
  for (const d of [dataDir(), jobsDir(), modelsDir()]) {
    mkdirSync(d, { recursive: true })
  }
}
