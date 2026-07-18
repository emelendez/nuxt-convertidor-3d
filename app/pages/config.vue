<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()
const toast = useToast()

onMounted(() => { if (!store.probe) navigateTo('/') })

const loading = ref(true)
const rows = ref<any[]>([])
const outputs = ref<Record<string, any>>({})
const depthModels = ref<Record<string, any>>({})
const engines = ref<any[]>([])

async function loadEstimate() {
  if (!store.probe) return
  loading.value = true
  try {
    const r: any = await api.estimate({
      duration_s: store.probe.duration_s,
      fps: store.probe.video?.fps || 24,
      inpaint_steps: store.cfg.inpaint_steps,
    })
    store.estimate = r
    rows.value = r.rows
    outputs.value = r.outputs
    depthModels.value = r.depth_models
    engines.value = r.engines || []
    store.unlockStep(3)
  } catch (e: any) {
    toast.add({ title: 'No se pudo estimar', description: e.message, color: 'error' })
  } finally {
    loading.value = false
  }
}
onMounted(loadEstimate)

const procItems = [{ label: '1080p', value: '1080p' }, { label: '4K', value: '4k' }]
// modos = motores de estereo que reporta el worker (addons incluidos); sin
// worker instalado, los dos clasicos de siempre
const modeItems = computed(() => {
  const stereo = engines.value.filter((e: any) => e.stage === 'stereo')
  if (!stereo.length) return [{ label: '⚡ Rápido', value: 'fast' }, { label: '💎 Calidad', value: 'hq' }]
  return stereo.map((e: any) => ({
    label: modeLabel(engineToMode(e.id), engines.value),
    value: engineToMode(e.id),
    disabled: !e.available,
  }))
})
const depthItems = computed(() => Object.entries(depthModels.value).map(([value, m]: any) => ({ label: m.label, value })))
const outputItems = computed(() => Object.entries(outputs.value).map(([value, o]: any) => ({ label: o.label, value })))

const current = computed(() => rows.value.find(r =>
  r.proc_res === store.cfg.proc_res && r.depth_model === store.cfg.depth_model
  && r.mode === store.cfg.mode && r.output === store.cfg.output))

const statusColor: Record<string, any> = { ok: 'success', warn: 'warning', no: 'error' }
const statusLabel: Record<string, string> = { ok: '✓ viable', warn: '⚠ con ajustes', no: '✗ inviable' }
</script>

<template>
  <div class="flex flex-col gap-6">
    <UCard>
      <template #header><h2 class="font-semibold">2 · Configuración</h2></template>

      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <UFormField label="Resolución de proceso">
          <USelect v-model="store.cfg.proc_res" :items="procItems" class="w-full" />
        </UFormField>
        <UFormField label="Modelo de profundidad">
          <USelect v-model="store.cfg.depth_model" :items="depthItems" class="w-full" />
        </UFormField>
        <UFormField label="Modo">
          <USelect v-model="store.cfg.mode" :items="modeItems" class="w-full" />
        </UFormField>
        <UFormField label="Salida (SBS)">
          <USelect v-model="store.cfg.output" :items="outputItems" class="w-full" />
        </UFormField>
      </div>
    </UCard>

    <UCard v-if="current">
      <template #header><h3 class="font-semibold">Estimación para tu selección</h3></template>
      <div class="grid sm:grid-cols-4 gap-4 text-sm">
        <div><p class="text-muted">Estado</p><UBadge :color="statusColor[current.status]" variant="subtle" :label="statusLabel[current.status]" /></div>
        <div><p class="text-muted">Demo (60 s)</p><p class="font-semibold">{{ fmtDuration(current.demo_seconds) }}</p></div>
        <div><p class="text-muted">Película completa</p><p class="font-semibold">{{ fmtDuration(current.full_seconds) }}</p></div>
        <div><p class="text-muted">VRAM</p><p class="font-semibold">{{ current.vram_needed_gb }} GB{{ current.calibrated ? ' · calibrado' : '' }}</p></div>
      </div>
      <ul v-if="current.notes?.length" class="mt-3 text-xs text-muted list-disc list-inside space-y-0.5">
        <li v-for="(n, i) in current.notes" :key="i">{{ n }}</li>
      </ul>
      <template #footer>
        <div class="flex justify-between items-center">
          <p v-if="loading" class="text-xs text-muted">Calculando…</p><span v-else />
          <UButton color="primary" trailing-icon="i-lucide-arrow-right" to="/demo" :disabled="current.status === 'no'">
            Continuar → Demo
          </UButton>
        </div>
      </template>
    </UCard>

    <UCard>
      <template #header><h3 class="font-semibold">Todas las combinaciones ({{ rows.length }})</h3></template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="text-muted text-left">
            <tr class="border-b border-default">
              <th class="py-2 pr-3">Proceso</th><th class="pr-3">Modelo</th><th class="pr-3">Modo</th>
              <th class="pr-3">Salida</th><th class="pr-3">Estado</th><th class="pr-3">Demo</th>
              <th class="pr-3">Completa</th><th class="pr-3">VRAM</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in rows" :key="i"
              class="border-b border-default/50 hover:bg-elevated cursor-pointer"
              @click="Object.assign(store.cfg, { proc_res: r.proc_res, depth_model: r.depth_model, mode: r.mode, output: r.output })"
            >
              <td class="py-1.5 pr-3">{{ r.proc_res }}</td>
              <td class="pr-3">{{ depthModelLabel(r.depth_model) }}</td>
              <td class="pr-3">{{ modeLabel(r.mode, engines) }}</td>
              <td class="pr-3">{{ outputs[r.output]?.label || r.output }}</td>
              <td class="pr-3"><UBadge :color="statusColor[r.status]" variant="subtle" size="sm" :label="statusLabel[r.status]" /></td>
              <td class="pr-3">{{ fmtDuration(r.demo_seconds) }}</td>
              <td class="pr-3">{{ fmtDuration(r.full_seconds) }}</td>
              <td class="pr-3">{{ r.vram_needed_gb }} GB</td>
            </tr>
          </tbody>
        </table>
      </div>
    </UCard>
  </div>
</template>
