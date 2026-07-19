// Estado global (refleja frontend/src/state.js) con Pinia.
import { defineStore } from 'pinia'

export interface Cfg {
  proc_res: string
  depth_model: string
  mode: string
  inpaint_steps: number
  output: string
  divergence: number
  convergence: number
  tonemap: boolean
  // Opcionales: los precarga un perfil de renderizado y/o el panel "Ajustes
  // avanzados". Sus defaults igualan a los del worker, asi que estar presentes
  // con estos valores no cambia el comportamiento. Viajan verbatim al worker.
  profile?: string
  engines?: { depth?: string, stereo?: string }
  sharpen?: number
  sharpen_radius?: number
  depth_smooth?: boolean
  depth_smooth_strength?: number
  telea_radius?: number
  inpaint_downscale?: boolean
  vram_ok?: boolean
}

export interface Profile {
  id: string
  label: string
  description?: string
  cfg: Partial<Cfg>
}

export const useAppStore = defineStore('app', {
  state: () => ({
    maxStep: 1 as number,
    health: null as any,
    probe: null as any,
    estimate: null as any,
    cfg: {
      proc_res: '4k',
      depth_model: 'vda_s',
      mode: 'fast',
      inpaint_steps: 8,
      output: 'hsbs_4k',
      divergence: 2.0,
      convergence: 0.5,
      tonemap: true,
      // defaults de knobs avanzados (identicos a los del worker)
      profile: 'default',
      sharpen: 0.0,
      sharpen_radius: 1.0,
      depth_smooth: true,
      depth_smooth_strength: 0.6,
      telea_radius: 3,
      inpaint_downscale: true,
      vram_ok: true,
    } as Cfg,
    profiles: [] as Profile[],
    selectedProfile: 'default',
    demo: { start_mode: 'fixed', start_s: 600, duration_s: 60 },
    jobs: {} as Record<string, any>,
    outputFiles: [] as any[],
  }),
  getters: {
    activeJobs: state => Object.values(state.jobs).filter((j: any) => j.state === 'running' || j.state === 'queued'),
    completedCount: state => state.outputFiles.length,
    // true hasta que /api/health diga lo contrario (local es el caso comun);
    // gobierna que acciones fisicamente locales se muestran (Explorer, etc.).
    isLocalClient: state => state.health?.client_is_local !== false,
    lanUrls: state => (state.health?.lan_urls || []) as string[],
    // true hasta que /api/health diga lo contrario (no bloquear durante la
    // carga); false = falta el worker de IA (.venv), no se puede generar 3D.
    workerInstalled: state => state.health?.worker_installed !== false,
  },
  actions: {
    unlockStep(n: number) { this.maxStep = Math.max(this.maxStep, n) },
    // Carga los parametros de un perfil de renderizado en el cfg activo.
    applyProfile(p: Profile) {
      if (!p) return
      Object.assign(this.cfg, structuredClone(toRaw(p.cfg)))
      this.cfg.profile = p.id
      this.selectedProfile = p.id
    },
    selectProfileById(id: string) {
      const p = this.profiles.find(x => x.id === id)
      if (p) this.applyProfile(p)
    },
    setProbe(p: any) { this.probe = p; if (p) this.unlockStep(2) },
    upsertJob(job: any) { this.jobs = { ...this.jobs, [job.id]: job } },
    setJobs(list: any[]) {
      const map: Record<string, any> = {}
      for (const j of list) map[j.id] = j
      this.jobs = map
    },
    setOutputFiles(files: any[]) { this.outputFiles = files },
  },
})
