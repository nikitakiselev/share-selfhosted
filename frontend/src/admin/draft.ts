import { ref } from 'vue'
import type { ExpiryPreset } from '@/lib/expiry'

/** Settings of a link not created yet: applied on the first file drop. */
export interface Draft {
  title: string
  preset: ExpiryPreset
  customAt: number | null
  password: string
}

/** Clicks on "New link" in the header while it's already open: the page starts over. */
export const newShareRequests = ref(0)
