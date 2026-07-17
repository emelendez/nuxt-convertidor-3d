<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()
const toast = useToast()

const path = ref('')
const analyzing = ref(false)
const browserOpen = ref(false)

// Subida desde el dispositivo del cliente (solo tiene sentido en remoto:
// en local la película ya está en el disco del servidor).
const uploadFile = ref<File | null>(null)
const uploading = ref(false)
const uploadPct = ref(0)

async function analyze(p?: string) {
  const target = (p ?? path.value).trim()
  if (!target) { toast.add({ title: 'Indica la ruta del fichero', color: 'warning' }); return }
  path.value = target
  analyzing.value = true
  try {
    const info = await api.probe(target)
    store.setProbe(info)
    toast.add({ title: 'Fichero analizado', color: 'success' })
  } catch (e: any) {
    toast.add({ title: 'No se pudo analizar', description: e.message, color: 'error' })
  } finally {
    analyzing.value = false
  }
}

watch(uploadFile, async (f) => {
  if (!f || uploading.value) return
  uploading.value = true
  uploadPct.value = 0
  try {
    const r = await api.uploadVideo(f, pct => { uploadPct.value = pct })
    toast.add({ title: 'Subida completada', description: r.name, color: 'success' })
    await analyze(r.path)
  } catch (e: any) {
    toast.add({ title: 'No se pudo subir', description: e.message, color: 'error' })
  } finally {
    uploading.value = false
    uploadFile.value = null
  }
})

const p = computed(() => store.probe)
</script>

<template>
  <div class="flex flex-col gap-6">
    <UCard>
      <template #header>
        <h2 class="font-semibold">1 · Elige la película</h2>
      </template>

      <p class="text-sm text-muted mb-4">
        {{ store.isLocalClient
          ? 'Selecciona un MKV/MP4 local (4K HEVC o 1080p). El fichero nunca sale de tu equipo.'
          : 'Selecciona un vídeo del servidor o sube uno desde este dispositivo. Todo se procesa en el servidor.' }}
      </p>

      <div class="flex flex-col sm:flex-row gap-2">
        <UInput
          v-model="path"
          class="flex-1"
          placeholder="C:\\videos\\pelicula.mkv"
          icon="i-lucide-file-video"
          @keyup.enter="analyze()"
        />
        <UButton color="neutral" variant="subtle" icon="i-lucide-folder-open" @click="browserOpen = true">
          Explorar…
        </UButton>
        <UButton color="primary" :loading="analyzing" icon="i-lucide-search" @click="analyze()">
          Analizar
        </UButton>
      </div>

      <div v-if="!store.isLocalClient" class="mt-4">
        <UProgress v-if="uploading" :model-value="uploadPct" status class="mb-2" />
        <UFileUpload
          v-model="uploadFile"
          accept="video/*,.mkv,.m2ts,.ts"
          icon="i-lucide-upload"
          label="…o arrastra aquí tu película"
          description="Se sube al servidor (misma red: rápido) y se convierte allí"
          :disabled="uploading"
          :preview="false"
        />
      </div>
    </UCard>

    <FileBrowser v-model:open="browserOpen" @select="analyze" />

    <UCard v-if="p">
      <template #header>
        <h3 class="font-semibold truncate" :title="p.filename">{{ p.filename }}</h3>
      </template>
      <dl class="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
        <div class="flex justify-between gap-4"><dt class="text-muted">Duración</dt><dd>{{ fmtDuration(p.duration_s) }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">Vídeo</dt><dd>{{ p.video?.width }}×{{ p.video?.height }} · {{ p.video?.codec }} · {{ p.video?.fps }} fps</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">HDR</dt><dd>{{ p.video?.hdr ? 'Sí (se hará tonemap a SDR)' : 'No' }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">Pistas audio / subs</dt><dd>{{ p.audio_tracks?.length ?? 0 }} / {{ p.subtitle_tracks?.length ?? 0 }}</dd></div>
      </dl>
      <template #footer>
        <div class="flex justify-end">
          <UButton color="primary" trailing-icon="i-lucide-arrow-right" to="/config">
            Continuar → Configuración
          </UButton>
        </div>
      </template>
    </UCard>
  </div>
</template>
