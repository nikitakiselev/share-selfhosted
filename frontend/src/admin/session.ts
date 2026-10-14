// Who is signed in. A 401 from any request returns to the sign-in form. Sign-in is open from
// anywhere; "forbidden" covers a server or proxy that closes access anyway.
import { reactive } from 'vue'
import { authApi } from '@/api/auth'
import type { User } from '@/api/types'
import { ApiError } from '@/lib/http'

export type SessionStatus = 'loading' | 'ok' | 'login' | 'forbidden' | 'offline'

export const session = reactive({ status: 'loading' as SessionStatus, user: null as User | null })

export async function checkSession(): Promise<void> {
  try {
    const info = await authApi.session()
    session.user = info.authenticated ? info.user : null
    session.status = info.authenticated ? 'ok' : 'login'
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) session.status = 'forbidden'
    else session.status = 'offline'
  }
}

/** Re-read the user without a loading screen: after a limit change, uploads, etc. */
export async function refreshUser(): Promise<void> {
  try {
    const info = await authApi.session()
    if (info.authenticated) session.user = info.user
    else signedOut()
  } catch {
    // next time
  }
}

export function signedOut(): void {
  session.user = null
  session.status = 'login'
}

/** Call in API request catch blocks. true — the session ended, the sign-in form is shown. */
export function handleAuthError(error: unknown): boolean {
  if (error instanceof ApiError && error.status === 401) {
    signedOut()
    return true
  }
  return false
}
