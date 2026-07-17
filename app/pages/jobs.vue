<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()
const toast = useToast()

const tab = ref<'queue' | 'completed'>('queue')
const previewSrc = ref('')
const previewTitle = ref('')
const previewStatus = ref('')

const jobsArr = computed(() => Object.values(store.jobs).sort((a: any, b: any) => b.created_at - a.created_at))
const running = computed(() => jobsArr.value.find((j: any) => j.state === 'running'))
const queued = computed(() => jobsArr.value.filter((j: any) => ['queued', 'running', 'paused'].includes(j.state)))
const outDir = computed(() => store.health?.settings?.output_dir || '')

function pct(j: any) {
  return j?.progress?.frames_total ? Math.round(100 * (j.progress.frames_done || 0) / j.progress.frames_total) : 0
}

async function cancel(id: string) {
  try { await api.cancelJob(id); toast.add({ title: 'Trabajo cancelado', color: 'success' }) }
  catch (e: any) { toast.add({ title: e.message, color: 'error' }) }
}

async function preview(f: any) {
  previewStatus.value = '⏳ Generando previsualización (unos segundos)…'
  previewTitle.value = f.name
  previewSrc.value = ''
  try {
    const r: any = await api.makeOutputPreview(f.path)
    previewSrc.value = `/api/output-files/preview/${r.name}`
    previewStatus.value = ''
  } catch (e: any) {
    previewStatus.value = `✗ ${e.message}`
    toast.add({ title: 'No se pudo previsualizar', description: e.message, color: 'error' })
  }
}

async function openFolder() {
  try { await api.openOutputDir() } catch (e: any) { toast.add({ title: e.message, color: 'error' }) }
}

async function del(f: any) {
  if (!confirm(`¿Borrar "${f.name}"? Esta acción no se puede deshacer.`)) return
  try {
    await api.deleteOutputFile(f.path)
    store.setOutputFiles(await api.getOutputFiles())
    toast.add({ title: 'Fichero borrado', color: 'success' })
  } catch (e: any) { toast.add({ title: e.message, color: 'error' }) }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <!-- Job activo -->
    <UCard v-if="running">
      <template #header>
        <div class="flex items-center gap-2 flex-wrap">
          <h3 class="font-semibold">▶ Convertidor en curso</h3>
          <UBadge :label="running.kind === 'demo' ? 'Demo' : 'Película completa'" variant="subtle" />
          <UButton class="ml-auto" size="xs" color="error" variant="subtle" icon="i-lucide-square" @click="cancel(running.id)">Cancelar</UButton>
        </div>
      </template>
      <p class="text-sm truncate mb-2" :title="running.filename">{{ running.filename }}</p>
      <UProgress :model-value="pct(running)" />
      <div class="grid grid-cols-4 gap-2 text-center text-xs mt-3">
        <div><p class="text-muted">Progreso</p><p class="font-semibold">{{ pct(running) }}%</p></div>
        <div><p class="text-muted">FPS</p><p class="font-semibold">{{ (running.progress?.fps || 0).toFixed(1) }}</p></div>
        <div><p class="text-muted">ETA</p><p class="font-semibold">{{ fmtDuration(running.progress?.eta_s) }}</p></div>
        <div><p class="text-muted">Etapa</p><p class="font-semibold truncate">{{ running.progress?.stage || '—' }}</p></div>
      </div>
    </UCard>

    <!-- Tabs -->
    <UCard>
      <template #header>
        <div class="flex items-center gap-2 flex-wrap">
          <h3 class="font-semibold">📚 Trabajos</h3>
          <div class="ml-auto flex rounded-lg overflow-hidden border border-default text-xs">
            <UButton size="xs" class="rounded-none" :variant="tab === 'queue' ? 'solid' : 'ghost'" :color="tab === 'queue' ? 'primary' : 'neutral'" @click="tab = 'queue'">
              En cola ({{ queued.length }})
            </UButton>
            <UButton size="xs" class="rounded-none" :variant="tab === 'completed' ? 'solid' : 'ghost'" :color="tab === 'completed' ? 'primary' : 'neutral'" @click="tab = 'completed'">
              Completadas ({{ store.outputFiles.length }})
            </UButton>
          </div>
        </div>
      </template>

      <!-- En cola -->
      <div v-if="tab === 'queue'">
        <p v-if="!queued.length" class="text-sm text-muted">No hay trabajos en cola.</p>
        <div v-for="j in queued" :key="j.id" class="p-3 border border-default rounded-lg mb-2">
          <div class="flex items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="text-sm font-medium truncate" :title="j.filename">{{ j.filename }}</p>
              <p class="text-xs text-muted">{{ j.cfg.depth_model.replace('vda_', 'VDA-') }} · {{ j.cfg.proc_res }} → {{ j.cfg.output }}</p>
            </div>
            <UBadge size="sm" variant="subtle" :color="j.state === 'running' ? 'success' : 'warning'" :label="j.state === 'running' ? '▶ En proceso' : '⏳ En cola'" />
            <UButton size="xs" color="error" variant="subtle" @click="cancel(j.id)">Cancelar</UButton>
          </div>
        </div>
      </div>

      <!-- Completadas -->
      <div v-else>
        <div class="flex items-center gap-2 mb-3 text-xs">
          <span class="text-muted shrink-0">📂 Carpeta de salida:</span>
          <code class="px-1.5 py-0.5 rounded bg-elevated font-mono truncate min-w-0" :title="outDir">{{ outDir || '—' }}</code>
          <!-- Abre Explorer EN el servidor: solo tiene sentido para el cliente local -->
          <UButton v-if="store.isLocalClient" class="ml-auto shrink-0" size="xs" color="neutral" variant="subtle" icon="i-lucide-folder-open" @click="openFolder">Abrir carpeta</UButton>
        </div>
        <p v-if="!store.outputFiles.length" class="text-sm text-muted">No hay conversiones completadas.</p>
        <div v-for="f in store.outputFiles" :key="f.path" class="p-3 border border-default rounded-lg mb-2">
          <div class="flex items-start justify-between gap-2 mb-2">
            <div class="min-w-0">
              <p class="text-sm font-medium truncate" :title="f.path">{{ f.name }}</p>
              <p class="text-xs text-muted">{{ fmtBytes(f.size_bytes) }} · {{ new Date(f.created_at * 1000).toLocaleString() }}</p>
            </div>
            <UBadge size="sm" variant="subtle" :color="f.is_demo ? 'info' : 'primary'" :label="f.is_demo ? '📺 Demo' : '🎬 Completa'" />
          </div>
          <div class="flex gap-2 justify-end">
            <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-eye" @click="preview(f)">Previsualizar</UButton>
            <!-- external: descarga nativa del navegador (attachment), fuera del router SPA -->
            <UButton size="xs" color="primary" variant="subtle" icon="i-lucide-download" :to="api.downloadOutputUrl(f.path)" external target="_self">Descargar</UButton>
            <UButton size="xs" color="error" variant="subtle" icon="i-lucide-trash-2" @click="del(f)">Borrar</UButton>
          </div>
        </div>
      </div>
    </UCard>

    <Preview3D :src="previewSrc" :title="previewTitle" :status="previewStatus" />
  </div>
</template>
