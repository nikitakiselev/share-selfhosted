// A fetch wrapper: JSON both ways, backend errors become ApiError with a code and a text.
import { formatSize } from './format'
import { hasMessage, type MessageKey, t } from './i18n'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly data: Record<string, unknown>

  constructor(status: number, code: string, message: string, data: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

const FALLBACK_MESSAGES: Record<number, MessageKey> = {
  401: 'errors.status401',
  403: 'errors.status403',
  404: 'errors.status404',
  410: 'errors.status410',
  413: 'errors.status413',
  429: 'errors.status429',
}

/**
 * Text for an error response: a translation by its `error` code, else the server's own
 * `message` (codes the interface doesn't know), else a text by HTTP status.
 */
export function apiErrorText(status: number, body: Record<string, unknown>): string {
  const key = `errors.${String(body.error)}`
  if (typeof body.error === 'string' && hasMessage(key)) {
    return t(key, {
      min: Number(body.min_length),
      max: Number(body.max_length),
      needed: formatSize(Number(body.needed)),
      free: formatSize(Number(body.free)),
      count: Math.ceil(Number(body.retry_after) / 60),
    })
  }
  if (typeof body.message === 'string' && body.message) return body.message
  const fallback = FALLBACK_MESSAGES[status]
  return fallback ? t(fallback) : t('errors.server', { status })
}

export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network', t('errors.network'))
  }
  if (response.status === 204) return undefined as T
  let data: unknown = null
  const text = await response.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (!response.ok) {
    const obj = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>
    const code = typeof obj.error === 'string' ? obj.error : `http_${response.status}`
    throw new ApiError(response.status, code, apiErrorText(response.status, obj), obj)
  }
  return data as T
}

export const http = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  delete: <T = void>(url: string) => request<T>('DELETE', url),
}
