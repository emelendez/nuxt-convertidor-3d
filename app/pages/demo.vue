<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()
const toast = useToast()

onMounted(() => { if (!store.probe) navigateTo('/') })

const launching = ref(false)
const previewSrc = ref('')
const previewTitle = ref('')

const startModes = [
  { value: 'fixed', label: 'Minuto 10' },
  { value: 'middle', label: 'Mitad' },
  { value: 'custom', label: 'Personalizado' },
]

async function launch() {
  launching.value = true
  try {
    await api.createJob({
      kind: 'demo', path: store.probe.path, cfg: store.cfg,
      demo_start_mode: store.demo.start_mode,
      demo_start_s: store.demo.start_s,
      demo_duration_s: store.demo.duration_s,
    })
    toast.add({ title: 'Demo en cola', color: 'success' })
  } catch (e: any) {
    toast.add({ title: 'No se pudo lanzar', description: e.message, color: 'error' })
  } finally {
    launching.value = false
  }
}

const demos = computed(() => Object.values(store.jobs)
  .filter((j: any) => j.kind === 'demo')
  .sort((a: any, b: any) => b.created_at - a.created_at))

function play(job: any) {
  previewSrc.value = `/api/jobs/${job.id}/preview?codec=h264`
  previewTitle.value = `${depthModelLabel(job.cfg.depth_model)} · ${job.cfg.output}`
}

function pct(j: any) {
  return j.progress?.frames_total ? Math.round(100 * (j.progress.frames_done || 0) / j.progress.frames_total) : 0
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <UCard>
      <template #header><h2 class="font-semibold">3 · Demo de prueba</h2></template>
      <p class="text-sm text-muted mb-4">Convierte un fragmento corto con la configuración actual para juzgar la calidad antes de la película completa.</p>
      <div class="grid sm:grid-cols-2 gap-4 items-end">
        <UFormField :label="`Duración: ${store.demo.duration_s} s`">
          <USlider v-model="store.demo.duration_s" :min="30" :max="180" :step="10" />
        </UFormField>
        <UFormField label="Punto de inicio">
          <div class="flex rounded-lg overflow-hidden border border-default w-fit">
            <UButton
              v-for="m in startModes" :key="m.value"
              size="sm" class="rounded-none"
              :variant="store.demo.start_mode === m.value ? 'solid' : 'ghost'"
              :color="store.demo.start_mode === m.value ? 'primary' : 'neutral'"
              @click="store.demo.start_mode = m.value"
            >{{ m.label }}</UButton>
          </div>
        </UFormField>
      </div>
      <template #footer>
        <UButton color="primary" icon="i-lucide-play" :loading="launching" @click="launch">
          Generar demo con la config actual
        </UButton>
      </template>
    </UCard>

    <UCard>
      <template #header><h3 class="font-semibold">🔬 Demos generadas</h3></template>
      <p v-if="!demos.length" class="text-sm text-muted">Aún no hay demos.</p>
      <div v-else class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <div v-for="j in demos" :key="j.id" class="border border-default rounded-xl p-3 text-sm">
          <div class="flex justify-between items-center gap-2">
            <span class="font-medium">{{ modeLabel(j.cfg.mode, store.health?.engines) }} · {{ depthModelLabel(j.cfg.depth_model) }} · {{ j.cfg.output }}</span>
            <UBadge size="sm" variant="subtle" :color="j.state === 'done' ? 'success' : j.state === 'error' ? 'error' : 'neutral'"
              :label="j.state === 'done' ? '✓ lista' : j.state === 'running' ? `${pct(j)}%` : j.state" />
          </div>
          <UProgress v-if="j.state === 'running'" :model-value="pct(j)" class="mt-2" size="sm" />
          <div class="flex gap-2 mt-2">
            <UButton v-if="j.state === 'done'" size="xs" color="primary" icon="i-lucide-eye" @click="play(j)">Ver</UButton>
            <UButton v-if="['queued', 'running'].includes(j.state)" size="xs" color="neutral" variant="subtle" @click="api.cancelJob(j.id)">Cancelar</UButton>
          </div>
        </div>
      </div>
    </UCard>

    <Preview3D :src="previewSrc" :title="previewTitle" />

    <div class="flex justify-end">
      <UButton color="primary" trailing-icon="i-lucide-arrow-right" to="/convert">Continuar → Conversión completa</UButton>
    </div>
  </div>
</template>
