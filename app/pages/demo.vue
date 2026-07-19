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

// Segundo de inicio efectivo del segmento — ESPEJO EXACTO de la resolución del
// backend (server/api/jobs/index.post.ts): fixed=min(600, dur*0.25),
// middle=centro, custom=start_s acotado. Se usa para la vista previa.
const resolvedStartS = computed(() => {
  const d = store.probe?.duration_s || 0
  const dur = Math.min(Math.max(store.demo.duration_s, 10), 300)
  const m = store.demo.start_mode
  if (m === 'middle') return Math.max(d / 2 - dur / 2, 0)
  if (m === 'custom') return Math.min(Math.max(store.demo.start_s || 0, 0), Math.max(d - dur, 0))
  return Math.min(600, d * 0.25)
})

// Campo manual "Personalizado": minuto ↔ segundos (store.demo.start_s).
const startMinute = computed({
  get: () => Math.round((store.demo.start_s || 0) / 60),
  set: (v: number) => { store.demo.start_s = Math.max(0, Math.round(Number(v) || 0)) * 60 },
})
const maxStartMinute = computed(() => {
  const d = store.probe?.duration_s || 0
  const dur = Math.min(Math.max(store.demo.duration_s, 10), 300)
  return Math.max(0, Math.floor((d - dur) / 60))
})

// Vista previa: 8 fotogramas repartidos por el segmento [inicio, inicio+duración].
const THUMB_COUNT = 8
const thumbTimestamps = computed(() => {
  const d = store.probe?.duration_s || 0
  const start = resolvedStartS.value
  const dur = Math.min(Math.min(Math.max(store.demo.duration_s, 10), 300), Math.max(d - start, 0))
  return Array.from({ length: THUMB_COUNT }, (_, i) =>
    Math.round(start + (dur * i) / Math.max(THUMB_COUNT - 1, 1)))
})

const thumbs = ref<(string | null)[]>([])
// Ítems del carrusel: cada uno = { t: segundo, b64: miniatura|null }.
const thumbItems = computed(() => thumbTimestamps.value.map((t, i) => ({ t, b64: thumbs.value[i] || null })))
const thumbsLoading = ref(false)
let thumbTimer: ReturnType<typeof setTimeout> | undefined

async function loadThumbs() {
  const path = store.probe?.path
  if (!path) { thumbs.value = []; return }
  thumbsLoading.value = true
  try {
    const r = await api.thumbnails(path, thumbTimestamps.value)
    thumbs.value = r.thumbnails || []
  } catch {
    thumbs.value = []  // degrada (p. ej. simulación / ffmpeg ausente): placeholders
  } finally {
    thumbsLoading.value = false
  }
}
// Debounce: el slider/campo disparan muchos cambios; recargamos al asentarse.
function scheduleThumbs() {
  clearTimeout(thumbTimer)
  thumbTimer = setTimeout(loadThumbs, 350)
}
watch([resolvedStartS, () => store.demo.duration_s], scheduleThumbs, { immediate: true })
onUnmounted(() => clearTimeout(thumbTimer))

function fmtTime(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.floor(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

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
          <div class="flex flex-col gap-2">
            <div class="flex rounded-lg overflow-hidden border border-default w-fit">
              <UButton
                v-for="m in startModes" :key="m.value"
                size="sm" class="rounded-none"
                :variant="store.demo.start_mode === m.value ? 'solid' : 'ghost'"
                :color="store.demo.start_mode === m.value ? 'primary' : 'neutral'"
                @click="store.demo.start_mode = m.value"
              >{{ m.label }}</UButton>
            </div>
            <div v-if="store.demo.start_mode === 'custom'" class="flex items-center gap-2">
              <UInputNumber v-model="startMinute" :min="0" :max="maxStartMinute" :step="1" class="w-32" />
              <span class="text-xs text-muted">minuto de inicio</span>
            </div>
          </div>
        </UFormField>
      </div>

      <div class="mt-4">
        <p class="text-xs text-muted mb-2">Vista previa de la escena · inicio en {{ fmtTime(resolvedStartS) }}</p>
        <UCarousel
          v-slot="{ item }"
          :items="thumbItems"
          :arrows="true"
          :ui="{ item: 'basis-42', container: 'gap-2' }"
          class="w-full"
        >
          <div class="relative w-full">
            <img
              v-if="item.b64"
              :src="`data:image/jpeg;base64,${item.b64}`"
              class="h-24 w-full rounded-md border border-default object-cover"
              :alt="`Fotograma en ${fmtTime(item.t)}`"
            >
            <div v-else class="h-24 w-full rounded-md border border-default bg-elevated animate-pulse" />
            <span class="absolute bottom-0 right-0 text-[10px] leading-none bg-black/60 text-white px-1 py-0.5 rounded-tl-md rounded-br-md">
              {{ fmtTime(item.t) }}
            </span>
          </div>
        </UCarousel>
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
