<script setup lang="ts">
import type { ViewMode } from '~/composables/useSbsRenderer'

const props = defineProps<{ src?: string, title?: string, status?: string }>()

const videoRef = ref<HTMLVideoElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const { mode, setMode, reset } = useSbsRenderer(canvasRef, videoRef)

const modes: { v: ViewMode, l: string }[] = [
  { v: 'sbs', l: 'SBS' },
  { v: 'anaglyph', l: 'Anaglifo 🔴🔵' },
  { v: 'interlaced', l: 'Entrelazado' },
]

watch(() => props.src, (s) => {
  reset()
  const v = videoRef.value
  if (v && s) { v.src = s; v.play().catch(() => {}) }
})
</script>

<template>
  <UCard v-show="src">
    <template #header>
      <div class="flex items-center gap-3 flex-wrap">
        <h3 class="font-semibold">👁️ Previsualización</h3>
        <p class="text-xs text-muted truncate min-w-0 max-w-full" :title="title">{{ title }}</p>
        <div class="ml-auto flex rounded-lg overflow-hidden border border-default">
          <UButton
            v-for="m in modes" :key="m.v"
            size="xs" :variant="mode === m.v ? 'solid' : 'ghost'"
            :color="mode === m.v ? 'primary' : 'neutral'" class="rounded-none"
            @click="setMode(m.v)"
          >{{ m.l }}</UButton>
        </div>
      </div>
    </template>

    <div class="relative bg-black rounded-xl overflow-hidden">
      <video ref="videoRef" class="w-full" controls muted loop crossorigin="anonymous" />
      <canvas
        ref="canvasRef"
        class="w-full absolute inset-0 pointer-events-none"
        :class="{ hidden: mode === 'sbs' }"
      />
    </div>
    <p class="text-xs text-muted mt-2">
      {{ status || 'SBS = como se ve en la TV; Anaglifo = 3D con gafas rojo-cian; Entrelazado = líneas alternas.' }}
    </p>
  </UCard>
</template>
