import { http } from '@/lib/http'
import type { SessionInfo, TokenInfo } from './types'

const token = (t: string) => `/api/auth/tokens/${encodeURIComponent(t)}`

export const authApi = {
  session: () => http.get<SessionInfo>('/api/auth/session'),
  login: (email: string, password: string) => http.post<void>('/api/auth/login', { email, password }),
  logout: () => http.post<void>('/api/auth/logout'),
  logoutAll: () => http.post<void>('/api/auth/logout-all'),
  changePassword: (current: string, next: string) => http.post<void>('/api/auth/password', { current, new: next }),
  /** Invitation or password reset: what kind of link and for whom. */
  token: (t: string) => http.get<TokenInfo>(token(t)),
  /** Invitation — { login, password } (login is the username), reset — { password }. Success signs in right away. */
  useToken: (t: string, body: { login?: string; password: string }) => http.post<void>(token(t), body),
  /** A one-time code for the desktop app; it exchanges the code and its PKCE verifier for a session. */
  appConnect: (challenge: string) => http.post<{ code: string; expires_in: number }>('/api/auth/app/connect', { challenge }),
}
