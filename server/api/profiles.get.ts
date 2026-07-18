import { listProfiles } from '../utils/profiles'

// Lista de perfiles de renderizado disponibles (profiles/*.json).
export default defineEventHandler(() => {
  return { profiles: listProfiles() }
})
