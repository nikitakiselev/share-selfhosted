// Storage: over the limit, how much still fits, the limit in GB for input fields.

export const GiB = 1024 ** 3

export interface QuotaLike {
  quota: number | null
  used: number
}

/** There is a limit and it is used up: new files can't be uploaded. */
export function isOverQuota(u: QuotaLike): boolean {
  return u.quota !== null && u.used >= u.quota
}

/** Used share 0…1; null — unlimited. */
export function quotaRatio(u: QuotaLike): number | null {
  if (u.quota === null) return null
  if (u.quota <= 0) return 1
  return Math.min(1, Math.max(0, u.used / u.quota))
}

/** How much still fits, minus what is queued but not yet counted by the server. null — unlimited. */
export function freeSpace(u: QuotaLike, pending = 0): number | null {
  if (u.quota === null) return null
  return Math.max(0, u.quota - u.used - pending)
}

/** The "Limit, GB" field and the "Unlimited" checkbox → bytes; null — unlimited, undefined — invalid. */
export function parseQuotaGb(gb: string, unlimited: boolean): number | null | undefined {
  if (unlimited) return null
  const value = gb.trim()
  if (!/^\d+$/.test(value) || Number(value) < 1) return undefined
  return Number(value) * GiB
}

/** Limit in bytes → whole GB for the field, at least 1. */
export function quotaToGb(bytes: number): number {
  return Math.max(1, Math.round(bytes / GiB))
}

/**
 * Which of the dropped files fit into the remaining space — in order, while they fit;
 * the rest aren't started, so as not to create uploads that are bound to fail.
 */
export function splitByQuota<T extends { size: number }>(
  files: readonly T[],
  free: number | null,
): { fit: T[]; skipped: T[]; skippedBytes: number } {
  if (free === null) return { fit: [...files], skipped: [], skippedBytes: 0 }
  const fit: T[] = []
  const skipped: T[] = []
  let left = free
  let skippedBytes = 0
  for (const file of files) {
    if (skipped.length === 0 && file.size <= left) {
      fit.push(file)
      left -= file.size
    } else {
      skipped.push(file)
      skippedBytes += file.size
    }
  }
  return { fit, skipped, skippedBytes }
}

/** A rough email check: the server checks it anyway. Compare after normalizeEmail. */
export function isEmail(raw: string): boolean {
  return raw.length <= 254 && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw)
}

export function normalizeEmail(raw: string): string {
  return raw.trim().toLowerCase()
}

/** Username by the server's rules — checked after normalizeLogin. */
export const LOGIN_RE = /^[a-z0-9._-]{3,32}$/
export const PASSWORD_MIN = 10

export function normalizeLogin(raw: string): string {
  return raw.trim().toLowerCase()
}
