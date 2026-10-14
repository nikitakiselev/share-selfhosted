// Sizes, dates and durations in the interface language.
import { getLocale, type MessageKey, t } from './i18n'

const UNITS: MessageKey[] = ['unit.b', 'unit.kb', 'unit.mb', 'unit.gb', 'unit.tb']

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—'
  let value = bytes
  let unit = 0
  // 1023.6 MB without a fraction would print as "1024 MB" — switch to the next unit earlier
  while (value >= 1023.5 && unit < UNITS.length - 1) {
    value /= 1024
    unit++
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1
  return `${value.toLocaleString(getLocale(), { maximumFractionDigits: digits })} ${t(UNITS[unit]!)}`
}

export function formatSpeed(bytesPerSecond: number): string {
  if (!bytesPerSecond || !Number.isFinite(bytesPerSecond)) return '—'
  return t('format.speed', { size: formatSize(bytesPerSecond) })
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = h ? String(m).padStart(2, '0') : String(m)
  return `${h ? `${h}:` : ''}${mm}:${String(sec).padStart(2, '0')}`
}

/** Upload time left: "3 min left", "40 s left", "1 h 5 min left". */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return ''
  const s = Math.ceil(seconds)
  if (s < 60) return t('eta.seconds', { n: s })
  const m = Math.round(s / 60)
  if (m < 60) return t('eta.minutes', { n: m })
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest ? t('eta.hoursMinutes', { h, m: rest }) : t('eta.hours', { h })
}

export function filesCount(n: number): string {
  return t('count.files', { count: n })
}

// Formatters are built per language on first use.
const dateFormats = new Map<string, Intl.DateTimeFormat>()

function dateFormat(name: 'date' | 'dateYear' | 'time' | 'full'): Intl.DateTimeFormat {
  const locale = getLocale()
  const key = `${locale}:${name}`
  let format = dateFormats.get(key)
  if (!format) {
    // 24-hour Russian time keeps the leading zero (09:05), English reads better as 9:05 AM
    const hour = locale === 'ru' ? '2-digit' : 'numeric'
    const options: Record<typeof name, Intl.DateTimeFormatOptions> = {
      date: { day: 'numeric', month: 'long' },
      dateYear: { day: 'numeric', month: 'long', year: 'numeric' },
      time: { hour, minute: '2-digit' },
      full: { day: 'numeric', month: 'short', year: 'numeric', hour, minute: '2-digit', second: '2-digit' },
    }
    format = new Intl.DateTimeFormat(locale, options[name])
    dateFormats.set(key, format)
  }
  return format
}

/** Unix seconds → "October 21, 2:30 PM" (the year only if it isn't the current one). */
export function formatDate(ts: number | null | undefined, withTime = true): string {
  if (ts == null) return '—'
  const d = new Date(ts * 1000)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  const date = dateFormat(sameYear ? 'date' : 'dateYear').format(d)
  return withTime ? `${date}, ${dateFormat('time').format(d)}` : date
}

export function formatDateFull(ts: number): string {
  return dateFormat('full').format(new Date(ts * 1000))
}

/** Unix seconds → "in 3 days", "5 minutes ago", "just now". */
export function formatRelative(ts: number | null | undefined, now = Date.now()): string {
  if (ts == null) return '—'
  const diff = ts - Math.round(now / 1000)
  const abs = Math.abs(diff)
  // a couple of seconds ahead is clock skew between server and browser, not the future
  if (abs < 45) return diff > 5 ? t('time.inAMinute') : t('time.justNow')
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['minute', 60],
    ['hour', 3600],
    ['day', 86400],
    ['week', 604800],
    ['month', 2592000],
    ['year', 31536000],
  ]
  let unit: Intl.RelativeTimeFormatUnit = 'minute'
  let size = 60
  for (const [u, s] of steps) {
    if (abs >= s) {
      unit = u
      size = s
    }
  }
  return new Intl.RelativeTimeFormat(getLocale(), { numeric: 'auto' }).format(Math.round(diff / size), unit)
}

/** Short browser and OS name from a User-Agent, for the activity log. */
export function shortUserAgent(ua: string | null | undefined): string {
  if (!ua) return '—'
  const os = /iPhone|iPad/.test(ua)
    ? 'iOS'
    : /Android/.test(ua)
      ? 'Android'
      : /Mac OS X|Macintosh/.test(ua)
        ? 'macOS'
        : /Windows/.test(ua)
          ? 'Windows'
          : /Linux/.test(ua)
            ? 'Linux'
            : ''
  let browser = ''
  if (/YaBrowser\//.test(ua)) browser = t('ua.yandex')
  else if (/Edg\//.test(ua)) browser = 'Edge'
  else if (/OPR\//.test(ua)) browser = 'Opera'
  else if (/Firefox\//.test(ua)) browser = 'Firefox'
  else if (/Chrome\//.test(ua) || /CriOS\//.test(ua)) browser = 'Chrome'
  else if (/Safari\//.test(ua)) browser = 'Safari'
  else if (/curl\//i.test(ua)) browser = 'curl'
  else if (/wget/i.test(ua)) browser = 'wget'
  if (!browser && !os) return ua.slice(0, 40)
  return [browser, os].filter(Boolean).join(', ')
}

export function fileExtension(name: string): string {
  const i = name.lastIndexOf('.')
  if (i <= 0 || i === name.length - 1) return ''
  return name.slice(i + 1).toUpperCase().slice(0, 5)
}
