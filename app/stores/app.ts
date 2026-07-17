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
    } as Cfg,
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
  },
  actions: {
    unlockStep(n: number) { this.maxStep = Math.max(this.maxStep, n) },
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
