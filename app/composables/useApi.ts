// Cliente REST sobre $fetch (equivale a frontend/src/api.js).
export function useApi() {
  async function req<T = any>(url: string, opts: Record<string, any> = {}): Promise<T> {
    try {
      return await $fetch<T>(url, opts)
    } catch (e: any) {
      const msg = e?.data?.statusMessage || e?.data?.message || e?.statusMessage || e?.message || 'Error de red'
      throw new Error(msg)
    }
  }
  // Subida con progreso: XHR porque fetch aun no expone upload.onprogress.
  function uploadVideo(file: File, onProgress: (pct: number) => void): Promise<{ path: string, name: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('PUT', `/api/upload?name=${encodeURIComponent(file.name)}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round(100 * e.loaded / e.total))
      }
      xhr.onload = () => {
        if (xhr.status < 300) { resolve(JSON.parse(xhr.responseText)); return }
        let msg = `Error ${xhr.status}`
        try { msg = JSON.parse(xhr.responseText).statusMessage || msg } catch {}
        reject(new Error(msg))
      }
      xhr.onerror = () => reject(new Error('Error de red durante la subida'))
      xhr.send(file)
    })
  }

  return {
    health: () => req('/api/health'),
    fsList: (dir?: string) => req(`/api/fs/list${dir ? `?dir=${encodeURIComponent(dir)}` : ''}`),
    uploadVideo,
    probe: (path: string) => req('/api/probe', { method: 'POST', body: { path } }),
    estimate: (body: Record<string, any>) => req('/api/estimate', { method: 'POST', body }),
    thumbnails: (path: string, timestamps: number[]) =>
      req('/api/thumbnails', { method: 'POST', body: { path, timestamps } }),
    createJob: (body: Record<string, any>) => req('/api/jobs', { method: 'POST', body }),
    jobs: () => req('/api/jobs'),
    getOutputFiles: (limit = 100): Promise<any[]> =>
      req<{ files: any[] }>(`/api/output-files?limit=${limit}`).then(r => r.files || []),
    makeOutputPreview: (path: string) => req('/api/output-files/preview', { method: 'POST', body: { path } }),
    // Constructor de URL (no llamada): se usa como href de descarga nativa.
    downloadOutputUrl: (path: string) => `/api/output-files/download?path=${encodeURIComponent(path)}`,
    openOutputDir: () => req('/api/open-output-dir', { method: 'POST' }),
    deleteOutputFile: (path: string) => req('/api/output-files/delete', { method: 'POST', body: { path } }),
    cancelJob: (id: string) => req(`/api/jobs/${id}/cancel`, { method: 'POST' }),
    settings: (body: Record<string, any>) => req('/api/settings', { method: 'POST', body }),
  }
}
