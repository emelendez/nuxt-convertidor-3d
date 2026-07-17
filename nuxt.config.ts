// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  modules: ['@nuxt/ui', '@pinia/nuxt'],

  // SPA: la app usa WebGPU/WebGL, <video>, EventSource y rutas de disco locales;
  // no hay beneficio de SSR y evita errores de hidratacion.
  ssr: false,

  css: ['~/assets/css/main.css'],
  devtools: { enabled: false },

  // Modo oscuro por clase .dark en <html> (como la app actual).
  colorMode: { classSuffix: '', preference: 'system', fallback: 'light' },

  // Escucha SOLO en local; mismo puerto que la app actual.
  devServer: { host: '127.0.0.1', port: 8765 },

  // Configuracion de runtime (server). Overrides en runtime SIN rebuild:
  //   NUXT_CONVERTIDOR3D_SIMULATE=true | NUXT_CONVERTIDOR3D_DATA_DIR=D:\datos
  //   NUXT_CONVERTIDOR3D_MODELS_DIR=... | NUXT_CONVERTIDOR3D_PYTHON_EXE=...
  // Tambien se aceptan las legacy CONVERTIDOR3D_* (fallback en server/utils/config.ts).
  // Defaults deliberadamente vacios: los reales se calculan EN RUNTIME en config.ts
  // (process.cwd()/homedir()); ponerlos aqui los hornearia en el build (no portable).
  runtimeConfig: {
    convertidor3d: {
      simulate: false,
      dataDir: '',
      modelsDir: '',
      pythonExe: '',
      // PIN de acceso remoto (NUXT_CONVERTIDOR3D_PIN; lo autogenera start.ps1).
      // Vacio = acceso remoto deshabilitado (fail-closed en middleware/auth.ts).
      pin: '',
    },
  },

  nitro: {
    preset: 'node-server',
    // Node 26 + @vercel/nft: el trazado de dependencias revienta (EISDIR en
    // readlink de ficheros normales). Esta app SIEMPRE corre desde su propia
    // carpeta (node_modules presente), asi que desactivamos el trazado: Node
    // resuelve las deps subiendo hasta el node_modules del proyecto.
    externals: { trace: false },
  },

  app: {
    head: {
      title: 'Convertidor 3D',
      htmlAttrs: { lang: 'es' },
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
    },
  },

  compatibilityDate: '2025-11-01',
})