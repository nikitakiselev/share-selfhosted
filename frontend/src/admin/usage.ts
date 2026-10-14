// User's storage: the header, the over-limit banner, the check before uploading.
import { computed, reactive } from 'vue'
import { appApi } from '@/api/app'
import type { Usage } from '@/api/types'
import { isOverQuota } from '@/lib/quota'
import { handleAuthError, session } from './session'

export const usage = reactive({ value: null as Usage | null })

export async function refreshUsage(): Promise<void> {
  try {
    usage.value = await appApi.usage()
  } catch (e) {
    handleAuthError(e)
  }
}

export function setUsage(value: Usage): void {
  usage.value = value
}

/** Until the first /usage response, storage comes from the session. */
export const currentUsage = computed(() => {
  if (usage.value) return usage.value
  const u = session.user
  if (!u) return null
  return {
    quota: u.quota,
    used: u.used,
    free: u.quota === null ? null : Math.max(0, u.quota - u.used),
    disk: null,
  } satisfies Usage
})

export const overQuota = computed(() => (currentUsage.value ? isOverQuota(currentUsage.value) : false))
