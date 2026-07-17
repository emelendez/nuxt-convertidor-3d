// Listado del disco DEL SERVIDOR para el explorador web (sustituye al dialogo
// nativo, que solo servia en la maquina servidora). Sin dir -> raices
// (unidades + accesos rapidos); con dir -> subcarpetas + ficheros de video.
// Sin confinamiento de ruta a proposito (el usuario elige su pelicula donde
// este); el acceso remoto lo gobierna el middleware de PIN.
import { existsSync } from 'node:fs'
import { readdir, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'pathe'
import { uploadsDir } from '../../utils/config'

const VIDEO_EXTS = new Set(['.mkv', '.mp4', '.m4v', '.mov', '.ts', '.m2ts'])
const ext = (n: string) => n.slice(n.lastIndexOf('.')).toLowerCase()

export default defineEventHandler(async (event) => {
  const dir = String(getQuery(event).dir || '')

  if (!dir) {
    const home = homedir()
    const quick = [
      { name: 'Vídeos', path: join(home, 'Videos') },
      { name: 'Descargas', path: join(home, 'Downloads') },
      { name: 'Subidas a la app', path: uploadsDir() },
      { name: 'Inicio', path: home },
    ].filter(q => existsSync(q.path))
    const drives: { name: string, path: string }[] = []
    for (const l of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') {
      if (existsSync(`${l}:/`)) drives.push({ name: `${l}:`, path: `${l}:/` })
    }
    return { roots: [...quick, ...drives] }
  }

  const base = resolve(dir)
  let entries
  try {
    entries = await readdir(base, { withFileTypes: true })
  } catch {
    throw createError({ statusCode: 400, statusMessage: 'No se puede leer esa carpeta' })
  }

  const dirs: string[] = []
  const files: { name: string, size_bytes: number }[] = []
  for (const e of entries) {
    // ocultar carpetas de sistema/puntos (ruido sin valor para elegir peliculas)
    if (e.name.startsWith('.') || e.name.startsWith('$') || e.name === 'System Volume Information') continue
    if (e.isDirectory()) {
      dirs.push(e.name)
    } else if (e.isFile() && VIDEO_EXTS.has(ext(e.name))) {
      const st = await stat(join(base, e.name)).catch(() => null)
      if (st) files.push({ name: e.name, size_bytes: st.size })
    }
  }
  const cmp = new Intl.Collator('es', { sensitivity: 'base' }).compare
  dirs.sort(cmp)
  files.sort((a, b) => cmp(a.name, b.name))

  const parent = dirname(base)
  return { dir: base, parent: parent !== base ? parent : null, dirs, files }
})
