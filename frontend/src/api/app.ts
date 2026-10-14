import { http } from '@/lib/http'
import type { AdminFile, AdminShareDetail, AdminShareSummary, ShareSettingsInput, Usage } from './types'

const share = (slug: string) => `/api/app/shares/${encodeURIComponent(slug)}`
const file = (slug: string, fileId: string) => `${share(slug)}/files/${encodeURIComponent(fileId)}`

/** Own links and files. The server answers 404 for others'. */
export const appApi = {
  usage: () => http.get<Usage>('/api/app/usage'),
  shares: () => http.get<{ shares: AdminShareSummary[]; usage: Usage }>('/api/app/shares'),
  createShare: (input: ShareSettingsInput) => http.post<AdminShareSummary>('/api/app/shares', input),
  share: (slug: string) => http.get<AdminShareDetail>(share(slug)),
  updateShare: (slug: string, input: ShareSettingsInput) => http.patch<AdminShareSummary>(share(slug), input),
  deleteShare: (slug: string) => http.delete(share(slug)),
  renameFile: (slug: string, fileId: string, name: string) => http.patch<AdminFile>(file(slug, fileId), { name }),
  deleteFile: (slug: string, fileId: string) => http.delete(file(slug, fileId)),
}
