<script setup lang="ts">
import { useAppStore } from '~/stores/app'

const store = useAppStore()
const api = useApi()

// Suscripcion global a eventos de jobs + polling de output-files.
useJobEvents()

onMounted(async () => {
  try {
    store.health = await api.health()
  } catch { /* backend no accesible: la UI degrada */ }
  try {
    // perfiles de renderizado: cargar la lista y aplicar el 'default' (o el
    // primero) para sembrar el cfg antes de que el usuario elija pelicula.
    const { profiles } = await api.profiles()
    store.profiles = profiles || []
    const def = store.profiles.find(p => p.id === store.selectedProfile) || store.profiles[0]
    if (def) store.applyProfile(def)
  } catch { /* sin perfiles: se usan los defaults del store */ }
})
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
