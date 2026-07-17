import { manager } from '../../utils/jobs'

export default defineEventHandler(() => {
  return { jobs: manager.listJobs().map(j => manager.publicJob(j)) }
})
