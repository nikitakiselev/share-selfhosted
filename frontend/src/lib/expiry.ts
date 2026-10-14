// Link expiration: presets and remembering the last choice.
import type { MessageKey } from './i18n'

export type ExpiryPreset = '1h' | '1d' | '7d' | '30d' | 'never' | 'custom'

export const EXPIRY_PRESETS: { id: Exclude<ExpiryPreset, 'custom'>; label: MessageKey; seconds: number | null }[] = [
  { id: '1h', label: 'expiry.1h', seconds: 3600 },
  { id: '1d', label: 'expiry.1d', seconds: 86400 },
  { id: '7d', label: 'expiry.7d', seconds: 7 * 86400 },
  { id: '30d', label: 'expiry.30d', seconds: 30 * 86400 },
  { id: 'never', label: 'expiry.never', seconds: null },
]

/** How long files live after the link expires — a window to extend it. */
export const GRACE_SECONDS = 7 * 86400

const STORAGE_KEY = 'share:expiry-preset'
const DEFAULT: ExpiryPreset = '7d'

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

export function expiresAtFor(preset: ExpiryPreset, customAt: number | null): number | null {
  if (preset === 'custom') return customAt
  const found = EXPIRY_PRESETS.find((p) => p.id === preset)
  return found?.seconds == null ? null : nowSeconds() + found.seconds
}

export function loadPreset(): ExpiryPreset {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value && EXPIRY_PRESETS.some((p) => p.id === value)) return value as ExpiryPreset
  } catch {
    // localStorage is unavailable
  }
  return DEFAULT
}

export function savePreset(preset: ExpiryPreset): void {
  if (preset === 'custom') return
  try {
    localStorage.setItem(STORAGE_KEY, preset)
  } catch {
    // not a problem
  }
}

/** Unix seconds ↔ an <input type="datetime-local"> value in local time. */
export function toLocalInput(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromLocalInput(value: string): number | null {
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null
}
