import { http } from '@/lib/http'
import type { AdminUser, CreatedInvite, Invite, UserUpdate, UsersResponse } from './types'

const user = (id: number) => `/api/admin/users/${id}`

/** User management: admin role and the internal network only, otherwise 403. */
export const adminApi = {
  users: () => http.get<UsersResponse>('/api/admin/users'),
  updateUser: (id: number, input: UserUpdate) => http.patch<AdminUser>(user(id), input),
  deleteUser: (id: number) => http.delete(user(id)),
  resetLink: (id: number) => http.post<{ url: string; expires_at: number }>(`${user(id)}/reset`),
  invites: () => http.get<{ invites: Invite[] }>('/api/admin/invites'),
  /** A repeated invitation to the same email replaces the previous one. */
  createInvite: (input: { email: string; quota: number | null }) => http.post<CreatedInvite>('/api/admin/invites', input),
  /** A new link replacing the previous one, valid for 7 days again. */
  renewInvite: (id: number) => http.post<CreatedInvite>(`/api/admin/invites/${id}/renew`),
  revokeInvite: (id: number) => http.delete(`/api/admin/invites/${id}`),
}
