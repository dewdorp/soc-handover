/**
 * 장비 비밀번호 보관 API.
 *
 * 비밀번호 값은 reveal() 응답에만 들어 있다. 목록 · 상세 · 이력에는 없다.
 */
import { api, request } from './client'

export type CredentialScope = 'SHARED' | 'PERSONAL'

export interface Credential {
  id: number
  scope: CredentialScope
  company_id: number | null
  company: string | null
  device_name: string
  access_method: string | null
  username: string | null
  note: string | null
  owner_id: number
  owner: string | null
  rotated_at: string | null
  rotated_by: string | null
  current_version_no: number
  can_edit: boolean
  created_at: string
  updated_at: string
}

export interface CredentialVersion {
  version_no: number
  changed_fields: string[]
  changed_by: string | null
  changed_at: string
  change_note: string | null
  device_name: string | null
  username: string | null
  has_secret: boolean
}

export interface RevealResult {
  credential_id: number
  version_no: number
  secret: string
  device_name: string
  username: string | null
}

export interface CredentialInput {
  scope?: CredentialScope
  company_id?: number | null
  device_name?: string
  access_method?: string | null
  username?: string | null
  secret?: string
  note?: string | null
  change_note?: string | null
}

const P = '/credentials'

export interface VaultSessionResult {
  token: string
  expires_in_seconds: number
  remaining_absolute_seconds: number
}
export type VaultTimes = Pick<VaultSessionResult, 'expires_in_seconds' | 'remaining_absolute_seconds'>

export const credentialApi = {
  unlockVault: (password: string) =>
    api.post<VaultSessionResult>(`${P}/vault/unlock`, { password }),
  vaultSecrets: (token: string, ids: number[]) => {
    const qs = new URLSearchParams()
    ids.forEach(id => qs.append('ids', String(id)))
    return request<RevealResult[]>(`${P}/vault/secrets?${qs.toString()}`, {
      method: 'GET', headers: {'X-Vault-Token': token},
    })
  },
  extendVault: (token: string) =>
    request<VaultTimes>(`${P}/vault/extend`, { method: 'POST', headers: {'X-Vault-Token': token} }),
  lockVault: (token: string) =>
    request<void>(`${P}/vault/lock`, { method: 'POST', headers: {'X-Vault-Token': token} }),
  list: (params: { q?: string; scope?: CredentialScope | ''; company_id?: number | null } = {}) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.scope) qs.set('scope', params.scope)
    if (params.company_id) qs.set('company_id', String(params.company_id))
    return api.get<Credential[]>(`${P}${qs.toString() ? `?${qs}` : ''}`)
  },
  create: (body: CredentialInput) => api.post<Credential>(P, body),
  update: (id: number, body: CredentialInput) => api.patch<Credential>(`${P}/${id}`, body),
  remove: (id: number) => api.delete<void>(`${P}/${id}`),
  history: (id: number) => api.get<CredentialVersion[]>(`${P}/${id}/versions`),
  /** 지금 비밀번호 보기 — 본인 계정 비밀번호가 필요하고, 한 건씩 감사에 남는다 */
  reveal: (id: number, password: string) =>
    api.post<RevealResult>(`${P}/${id}/reveal`, { password }),
  /** 바꾸기 전 비밀번호 보기(장비에 새 값이 안 먹었을 때) */
  revealVersion: (id: number, versionNo: number, password: string) =>
    api.post<RevealResult>(`${P}/${id}/versions/${versionNo}/reveal`, { password }),
}
