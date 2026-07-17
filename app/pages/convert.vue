<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()
const toast = useToast()

onMounted(() => { if (!store.probe) navigateTo('/') })

const launching = ref(false)
async function launch() {
  launching.value = true
  try {
    await api.createJob({ kind: 'full', path: store.probe.path, cfg: store.cfg })
    toast.add({ title: 'Conversión en cola', color: 'success' })
    navigateTo('/jobs')
  } catch (e: any) {
    toast.add({ title: 'No se pudo lanzar', description: e.message, color: 'error' })
  } finally {
    launching.value = false
  }
}
const cfg = computed(() => store.cfg)
</script>

<template>
  <div class="flex flex-col gap-6">
    <UCard>
      <template #header><h2 class="font-semibold">4 · Conversión completa</h2></template>
      <dl class="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
        <div class="flex justify-between gap-4"><dt class="text-muted">Película</dt><dd class="truncate" :title="store.probe?.filename">{{ store.probe?.filename }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">Modo</dt><dd>{{ cfg.mode === 'hq' ? `💎 Calidad (${cfg.inpaint_steps} pasos)` : '⚡ Rápido' }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">Modelo</dt><dd>{{ cfg.depth_model.replace('vda_', 'VDA-').toUpperCase() }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-muted">Proceso / Salida</dt><dd>{{ cfg.proc_res }} → {{ cfg.output }}</dd></div>
      </dl>
      <template #footer>
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <p class="text-xs text-muted">La conversión es reanudable: puedes cerrar la app y retomarla relanzando el mismo trabajo.</p>
          <UButton color="primary" size="lg" icon="i-lucide-play" :loading="launching" @click="launch">
            Convertir película completa
          </UButton>
        </div>
      </template>
    </UCard>

    <UAlert
      icon="i-lucide-tv"
      color="neutral"
      variant="subtle"
      title="Cómo verlo en tu LG 3D"
      description="Copia el MKV a un USB (NTFS para >4 GB), reprodúcelo en la TV, pulsa el botón 3D del mando y elige Side by Side. Recomendado: Half-SBS 4K."
    />
  </div>
</template>
