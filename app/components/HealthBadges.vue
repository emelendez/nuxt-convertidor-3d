<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const h = computed(() => store.health)

// La conversion corre SIEMPRE en el servidor: se etiqueta como "GPU del
// servidor" para que un cliente remoto no crea que se usa la suya.
const computeLabel = computed(() => {
  const hi = h.value
  if (!hi) return null
  const gpu = hi.gpus?.[0]
  if (gpu) return { label: gpu.name.replace('NVIDIA GeForce ', ''), color: 'success' as const, tip: `GPU del servidor · ${gpu.vram_gb} GB VRAM · CUDA` }
  const c = hi.compute
  if (c && c.kind !== 'cpu') return { label: (c.name || 'GPU').replace('AMD Radeon(TM)', 'Radeon'), color: 'warning' as const, tip: ['GPU del servidor', ...(c.notes || [])].join(' · ') }
  return { label: 'Solo CPU', color: 'warning' as const, tip: ['CPU del servidor', ...(c?.notes || [])].join(' · ') }
})
</script>

<template>
  <div v-if="h" class="flex items-center gap-1.5 text-xs">
    <UBadge v-if="h.simulate" color="warning" variant="subtle" label="SIMULACIÓN" />
    <UTooltip v-if="computeLabel" :text="computeLabel.tip">
      <UBadge :color="computeLabel.color" variant="subtle" :label="computeLabel.label" />
    </UTooltip>
    <UTooltip :text="h.components?.ffmpeg ? `Encoder: ${h.components?.encoder || '?'}` : 'Ejecuta setup.ps1'">
      <UBadge :color="h.components?.ffmpeg ? 'success' : 'error'" variant="subtle" label="FFmpeg" />
    </UTooltip>
    <UTooltip :text="h.components?.depth === 'vda' ? 'Video Depth Anything (CUDA)' : h.components?.depth === 'onnx' ? 'Depth Anything V2 ONNX (DirectML/CPU)' : 'Faltan modelos'">
      <UBadge :color="h.components?.depth ? 'success' : 'error'" variant="subtle" label="IA" />
    </UTooltip>
  </div>
</template>
