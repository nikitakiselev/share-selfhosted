import { http } from '@/lib/http'
import type { PublicShare } from './types'

const base = (slug: string) => `/api/public/shares/${encodeURIComponent(slug)}`

export const publicApi = {
  share: (slug: string) => http.get<PublicShare>(base(slug)),
  unlock: (slug: string, password: string) => http.post<void>(`${base(slug)}/unlock`, { password }),
  zipUrl: (slug: string) => `${base(slug)}/zip`,
  /** A "play" event: a beacon, so it isn't lost when leaving the page. */
  played(slug: string, fileId: string) {
    const url = `${base(slug)}/files/${encodeURIComponent(fileId)}/played`
    try {
      if (navigator.sendBeacon?.(url)) return
    } catch {
      // fall back to fetch below
    }
    void fetch(url, { method: 'POST', keepalive: true, credentials: 'same-origin' }).catch(() => {})
  },
}
