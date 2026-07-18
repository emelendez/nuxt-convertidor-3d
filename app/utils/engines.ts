// Formateo centralizado de nombres de motores/modelos para la UI.
// (antes: .replace('vda_', 'VDA-') duplicado en 4 paginas + HealthBadges)

// mode legacy <-> id de motor (espejo de server/utils/estimator.ts)
export const MODE_TO_ENGINE: Record<string, string> = { fast: 'stereo_fast', hq: 'stereo_sc_svd' }
export function modeToEngine(mode: string): string { return MODE_TO_ENGINE[mode] ?? mode }
export function engineToMode(id: string): string {
  return id === 'stereo_fast' ? 'fast' : id === 'stereo_sc_svd' ? 'hq' : id
}

const MODE_FALLBACK: Record<string, string> = { fast: '⚡ Rápido', hq: '💎 Calidad' }

// Etiqueta de un modo/motor de estéreo: usa el label del manifest si los
// motores (de /api/health o /api/estimate) están disponibles.
export function modeLabel(mode: string, engines?: any[] | null): string {
  const id = modeToEngine(mode)
  const eng = engines?.find((e: any) => e.id === id)
  if (eng?.label) {
    return mode === 'fast' ? `⚡ ${eng.label}` : mode === 'hq' ? `💎 ${eng.label}` : eng.label
  }
  return MODE_FALLBACK[mode] ?? mode
}

// Etiqueta corta del modelo de profundidad (vda_s -> VDA-S)
export function depthModelLabel(dm: string): string {
  return String(dm || '').replace('vda_', 'VDA-').toUpperCase()
}
