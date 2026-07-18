// Perfiles de renderizado: ficheros JSON descubribles en profiles/ que
// preconfiguran de una vez todos los knobs del pipeline (cfg). Modular como un
// addon: un tercero añade un perfil soltando un profiles/<id>.json. La UI los
// lista, autoselecciona 'default' y aplica el elegido a store.cfg. Node no
// interpreta el cfg: solo lo sirve; viaja verbatim al worker via el jobspec.
import { readdirSync, readFileSync } from 'node:fs'
import { basename, join } from 'pathe'
import { ROOT_DIR } from './config'

export interface Profile {
  id: string
  label: string
  description?: string
  cfg: Record<string, any>
}

const PROFILES_DIR = join(ROOT_DIR, 'profiles')

let _cache: Profile[] | null = null

// Descubre y valida los perfiles. Un JSON invalido no tumba al resto: se omite
// con un aviso. 'default' se ordena siempre el primero (es el autoseleccionado).
export function listProfiles(): Profile[] {
  if (_cache) return _cache
  const out: Profile[] = []
  let files: string[] = []
  try {
    files = readdirSync(PROFILES_DIR).filter(f => f.endsWith('.json'))
  } catch {
    _cache = out
    return out
  }
  for (const f of files.sort()) {
    const id = basename(f, '.json')
    try {
      const data = JSON.parse(readFileSync(join(PROFILES_DIR, f), 'utf-8'))
      if (data?.id !== id) { console.warn(`[profiles] ${f}: 'id' debe ser "${id}"; omitido`); continue }
      if (typeof data.cfg !== 'object' || data.cfg === null) { console.warn(`[profiles] ${f}: falta 'cfg' (objeto); omitido`); continue }
      out.push({ id, label: String(data.label || id), description: data.description, cfg: data.cfg })
    } catch (e: any) {
      console.warn(`[profiles] ${f} ilegible: ${e?.message ?? e}; omitido`)
    }
  }
  out.sort((a, b) => (a.id === 'default' ? -1 : b.id === 'default' ? 1 : a.label.localeCompare(b.label)))
  _cache = out
  return out
}
