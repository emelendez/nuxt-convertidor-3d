<!-- Explorador del disco DEL SERVIDOR: sustituye al diálogo nativo (que solo
     tenía sentido en la máquina servidora). Funciona igual en local y remoto. -->
<script setup lang="ts">
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ select: [path: string] }>()

const api = useApi()
const toast = useToast()

const current = ref('')        // '' = raíces (unidades + accesos rápidos)
const roots = ref<any[]>([])
const dirs = ref<string[]>([])
const files = ref<any[]>([])
const parent = ref<string | null>(null)
const loading = ref(false)

async function load(dir: string) {
  loading.value = true
  try {
    const r: any = await api.fsList(dir || undefined)
    if (r.roots) {
      roots.value = r.roots
      dirs.value = []; files.value = []; parent.value = null
      current.value = ''
    } else {
      roots.value = []
      dirs.value = r.dirs; files.value = r.files; parent.value = r.parent
      current.value = r.dir
    }
  } catch (e: any) {
    toast.add({ title: 'No se pudo abrir la carpeta', description: e.message, color: 'error' })
  } finally {
    loading.value = false
  }
}

// carga inicial al abrir; al reabrir se conserva la última carpeta visitada
watch(open, (v) => { if (v && !current.value && !roots.value.length) load('') })

function joinPath(name: string) {
  return current.value.endsWith('/') || current.value.endsWith('\\')
    ? current.value + name
    : `${current.value}/${name}`
}

function pick(name: string) {
  emit('select', joinPath(name))
  open.value = false
}
</script>

<template>
  <UModal v-model:open="open" title="Elegir película del servidor" description="Vídeos MKV/MP4 del equipo donde corre la aplicación.">
    <template #body>
      <div class="flex flex-col gap-2 min-h-64 max-h-[60vh]">
        <div class="flex items-center gap-1.5">
          <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-hard-drive" :disabled="!current" @click="load('')">Unidades</UButton>
          <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-arrow-up" :disabled="!parent" @click="load(parent!)">Subir</UButton>
          <code v-if="current" class="text-xs px-1.5 py-1 rounded bg-elevated truncate min-w-0" :title="current">{{ current }}</code>
        </div>

        <div class="overflow-y-auto flex-1 border border-default rounded-lg divide-y divide-default/50">
          <p v-if="loading" class="p-3 text-sm text-muted">Cargando…</p>
          <template v-else-if="roots.length">
            <button
              v-for="r in roots" :key="r.path" type="button"
              class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-elevated"
              @click="load(r.path)"
            >
              <UIcon name="i-lucide-hard-drive" class="text-muted shrink-0" />
              <span class="truncate">{{ r.name }}</span>
              <span class="text-xs text-muted ml-auto truncate">{{ r.path }}</span>
            </button>
          </template>
          <template v-else>
            <button
              v-for="d in dirs" :key="d" type="button"
              class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-elevated"
              @click="load(joinPath(d))"
            >
              <UIcon name="i-lucide-folder" class="text-warning shrink-0" />
              <span class="truncate">{{ d }}</span>
            </button>
            <button
              v-for="f in files" :key="f.name" type="button"
              class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-elevated"
              @click="pick(f.name)"
            >
              <UIcon name="i-lucide-file-video" class="text-primary shrink-0" />
              <span class="truncate">{{ f.name }}</span>
              <span class="text-xs text-muted ml-auto shrink-0">{{ fmtBytes(f.size_bytes) }}</span>
            </button>
            <p v-if="!dirs.length && !files.length" class="p-3 text-sm text-muted">
              Sin subcarpetas ni vídeos aquí.
            </p>
          </template>
        </div>
      </div>
    </template>
  </UModal>
</template>
