// Envuelve el renderer 3D (utils/renderer.js, INTACTO) en el ciclo de vida Vue.
import type { Ref } from 'vue'
import { createSbsRenderer } from '~/utils/renderer'

export type ViewMode = 'sbs' | 'anaglyph' | 'interlaced'

export function useSbsRenderer(
  canvasRef: Ref<HTMLCanvasElement | null>,
  videoRef: Ref<HTMLVideoElement | null>,
) {
  let renderer: any = null
  let raf: number | null = null
  const mode = ref<ViewMode>('sbs')
  const backend = ref<string>('')

  function stopLoop() {
    if (raf != null) { cancelAnimationFrame(raf); raf = null }
  }

  async function setMode(m: ViewMode) {
    mode.value = m
    const canvas = canvasRef.value
    const video = videoRef.value
    if (!canvas || !video) return
    if (m === 'sbs') { stopLoop(); return } // SBS = video crudo
    if (!renderer) {
      // Buffer con el aspecto del FRAME COMPLETO (no medio) para no recortar.
      canvas.width = video.videoWidth || 1920
      canvas.height = video.videoHeight || 1080
      renderer = await createSbsRenderer(canvas, video)
      if (!renderer) return
      backend.value = renderer.backend
    }
    renderer.setMode(m)
    const loop = () => {
      if (!video.isConnected) { raf = null; return }
      renderer.draw()
      raf = requestAnimationFrame(loop)
    }
    stopLoop()
    loop()
  }

  // Al cargar un nuevo video, descartar el renderer (dimensiones pueden cambiar).
  function reset() {
    stopLoop()
    renderer = null
    mode.value = 'sbs'
  }

  onUnmounted(() => { stopLoop(); renderer = null })

  return { mode, backend, setMode, reset }
}
