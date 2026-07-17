import { readdir, stat } from 'node:fs/promises'
import { join } from 'pathe'
import { outputDir } from '../../utils/config'

export default defineEventHandler(async (event) => {
  const limit = Number(getQuery(event).limit) || 100
  const dir = await outputDir()

  let entries: string[] = []
  try {
    entries = await readdir(dir, { recursive: true }) as unknown as string[]
  } catch { return { files: [] } } // el dir aun no existe

  const candidates = entries.filter(rel => rel.toLowerCase().endsWith('.mkv'))
  const files = (await Promise.all(candidates.map(async (rel) => {
    const full = join(dir, rel)
    try {
      const st = await stat(full)
      if (!st.isFile()) return null
      const name = rel.split(/[\\/]/).pop() || rel
      return {
        name,
        path: full,
        size_bytes: st.size,
        created_at: st.mtimeMs / 1000,
        is_demo: name.toLowerCase().includes('demo'),
      }
    } catch { return null }
  }))).filter(f => f !== null)

  files.sort((a, b) => b!.created_at - a!.created_at)
  return { files: files.slice(0, limit) }
})
