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
})
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
