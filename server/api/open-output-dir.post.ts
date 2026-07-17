import { outputDir } from '../utils/config'
import { ensureDir, openInSystem } from '../utils/fileActions'
import { assertLocal } from '../utils/security'

export default defineEventHandler(async (event) => {
  assertLocal(event)
  const dir = ensureDir(await outputDir())
  openInSystem(dir)
  return { ok: true, path: dir }
})
