<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const route = useRoute()
const colorMode = useColorMode()

const steps = [
  { n: 1, label: 'Archivo', to: '/' },
  { n: 2, label: 'Configuración', to: '/config' },
  { n: 3, label: 'Demo', to: '/demo' },
  { n: 4, label: 'Conversión', to: '/convert' },
]

const jobsBadge = computed(() => `${store.activeJobs.length}/${store.completedCount}`)

function toggleTheme() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}

// URLs para compartir con otros dispositivos (solo las ve el operador local).
const shareUrls = computed(() => {
  const pin = store.health?.remote_pin
  return store.lanUrls.map((u: string) => pin ? `${u}/?pin=${encodeURIComponent(pin)}` : u)
})
const copied = ref('')
async function copyUrl(u: string) {
  try { await navigator.clipboard.writeText(u); copied.value = u; setTimeout(() => { copied.value = '' }, 1500) }
  catch { /* clipboard no disponible (http remoto): queda el texto seleccionable */ }
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-default text-default">
    <header class="border-b border-default sticky top-0 z-40 bg-default/80 backdrop-blur">
      <div class="max-w-6xl mx-auto w-full px-4 py-3 flex items-center gap-3">
        <span class="text-2xl">🎬</span>
        <div class="min-w-0">
          <h1 class="font-semibold leading-tight">Convertidor 3D</h1>
          <p class="text-xs text-muted">2D → 3D SBS · cualquier TV 3D</p>
        </div>
        <HealthBadges class="ml-auto hidden sm:flex" />
        <!-- Acceso desde la red: solo el operador local ve las URLs (y el PIN) -->
        <UPopover v-if="store.isLocalClient && shareUrls.length">
          <UButton variant="ghost" color="neutral" icon="i-lucide-wifi" aria-label="Acceso desde la red" />
          <template #content>
            <div class="p-3 w-80 text-sm flex flex-col gap-2">
              <p class="font-semibold">Acceso desde la red</p>
              <template v-if="store.health?.remote_pin">
                <p class="text-xs text-muted">Comparte una de estas URLs (llevan el PIN incluido):</p>
                <div v-for="u in shareUrls" :key="u" class="flex items-center gap-1.5 min-w-0">
                  <code class="text-xs px-1.5 py-1 rounded bg-elevated truncate flex-1" :title="u">{{ u }}</code>
                  <UButton size="xs" color="neutral" variant="subtle" :icon="copied === u ? 'i-lucide-check' : 'i-lucide-copy'" aria-label="Copiar" @click="copyUrl(u)" />
                </div>
              </template>
              <p v-else class="text-xs text-muted">
                El acceso remoto está deshabilitado (sin PIN). Arranca con
                <code class="px-1 rounded bg-elevated">run.bat</code> — genera el PIN y lo muestra en la consola.
              </p>
            </div>
          </template>
        </UPopover>
        <UButton
          variant="ghost"
          color="neutral"
          :icon="colorMode.value === 'dark' ? 'i-lucide-sun' : 'i-lucide-moon'"
          aria-label="Cambiar tema"
          @click="toggleTheme"
        />
      </div>
    </header>

    <nav class="max-w-6xl mx-auto w-full px-4 pt-6 flex flex-wrap items-center gap-2">
      <UButton
        v-for="s in steps"
        :key="s.n"
        :to="s.n <= store.maxStep ? s.to : undefined"
        :disabled="s.n > store.maxStep"
        :variant="route.path === s.to ? 'solid' : 'ghost'"
        :color="route.path === s.to ? 'primary' : 'neutral'"
        size="sm"
      >
        <span
          class="w-5 h-5 rounded-full text-xs flex items-center justify-center"
          :class="route.path === s.to ? 'bg-white/20' : 'bg-elevated'"
        >{{ s.n }}</span>
        {{ s.label }}
      </UButton>

      <UButton
        to="/jobs"
        :variant="route.path === '/jobs' ? 'solid' : 'ghost'"
        :color="route.path === '/jobs' ? 'primary' : 'primary'"
        size="sm"
        class="ml-auto font-semibold"
      >
        🔥 Trabajos
        <UBadge :label="jobsBadge" variant="subtle" size="sm" />
      </UButton>
    </nav>

    <main class="flex-1 max-w-6xl mx-auto w-full px-4 py-6">
      <slot />
    </main>

    <footer class="max-w-6xl mx-auto w-full px-4 py-4 text-xs text-muted border-t border-default">
      {{ store.isLocalClient
        ? 'Procesamiento 100 % local — la película nunca sale de tu equipo.'
        : 'Procesamiento íntegro en el servidor de la aplicación — nada sube a la nube.' }}
      Modelos: Video Depth Anything (Apache-2.0 / CC-BY-NC-4.0) · StereoCrafter (no comercial).
    </footer>
  </div>
</template>
