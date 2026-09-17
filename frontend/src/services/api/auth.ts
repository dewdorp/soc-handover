import { api, request } from '@/services/api/client'
import type { Features, Me } from '@/types/api'

export const authApi = {
  login: (username: string, password: string) =>
    request<Me>('/auth/login', {
      method: 'POST',
      body: { username, password },
      retryOnUnauthorized: false,
    }),
  logout: () => api.post<void>('/auth/logout'),
  me: () => request<Me>('/auth/me', { retryOnUnauthorized: true }),
  changePassword: (current_password: string, new_password: string) =>
    api.post<void>('/auth/change-password', { current_password, new_password }),
  sessions: () => api.get<unknown[]>('/auth/sessions'),
}

export const systemApi = {
  features: () => api.get<Features>('/settings/features'),
  health: () => api.get<{ status: string; database: string }>('/health'),
}
