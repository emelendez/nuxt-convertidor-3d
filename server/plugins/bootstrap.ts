// Arranque del servidor (plugin SINCRONO: Nitro no espera plugins async):
//  1. monta el storage de la app (settings/calibration) sobre el data dir
//  2. antepone tools/ffmpeg/bin al PATH (ffmpeg embebido y portable)
//  3. crea los directorios de datos
import { existsSync } from 'node:fs'
import { delimiter, join } from 'pathe'
import fsLiteDriver from 'unstorage/drivers/fs-lite'
import { ROOT_DIR, dataDir, ensureDirs, saveSettings } from '../utils/config'

export default defineNitroPlugin(() => {
  // 'appdata' y NO 'data': Nitro ya monta 'data' (.data/kv) por defecto y
  // unstorage lanza una excepcion si se vuelve a montar sobre esa base.
  useStorage().mount('appdata', fsLiteDriver({ base: dataDir() }))

  // La mutacion de process.env.PATH es deliberadamente Node: los subprocesos
  // (ffmpeg, worker Python) heredan el PATH del proceso — no hay via web.
  const bin = join(ROOT_DIR, 'tools', 'ffmpeg', 'bin')
  if (existsSync(bin)) {
    process.env.PATH = bin + delimiter + (process.env.PATH || '')
  }
  ensureDirs()

  // Materializa el CONTRATO con el worker Python: settings.json debe existir
  // con output_dir, porque el worker lo lee por su cuenta y su default propio
  // (~/Videos) NO coincide con el de Node (data/conversions). Si el usuario ya
  // fijo un output_dir, se respeta. Fire-and-forget: el plugin es sincrono
  // (Nitro no espera plugins async) y los jobs llegan mucho despues del boot.
  void (async () => {
    const raw = await useStorage('appdata').getItem<Record<string, unknown>>('settings.json')
    if (!raw || typeof raw !== 'object' || !('output_dir' in raw)) {
      await saveSettings({})
    }
  })().catch(() => { /* data dir ilegible: la app sigue; el primer POST /settings lo reintenta */ })
})
