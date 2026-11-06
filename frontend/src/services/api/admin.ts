/** 감사 · 관리(사용자 · 코드 · 교대 · 설정 · 백업) · 댓글 · 첨부 · 통계 API (Phase 8, API.md §5-1). */
import { api, upload } from '@/services/api/client'
import type { Company, HandoverStatus, Page, Shift } from '@/types/api'

// ------------------------------------------------------------------ 감사

export interface AuditQuery {
  start: string
  end: string
  user_id?: number | null
  username?: string
  actions?: string[]
  hide_views?: boolean
  resource_type?: string
  resource_id?: string
  client_ip?: string
  result?: 'SUCCESS' | 'FAILURE' | null
  order?: 'desc' | 'asc'
  page?: number
  size?: number
}

export interface AuditRow {
  id: number
  occurred_at: string
  user_id: number | null
  username: string | null
  role_code: string | null
  client_ip: string | null
  user_agent: string | null
  request_id: string | null
  action: string
  action_label: string
  resource_type: string | null
  resource_id: string | null
  before_value: unknown
  after_value: unknown
  result: 'SUCCESS' | 'FAILURE'
  error_message: string | null
  detail: unknown
}

export interface AuditCatalog {
  groups: { name: string; actions: { code: string; label: string }[] }[]
  resource_types: string[]
  max_range_days: number
}

// ------------------------------------------------------------------ 관리

export interface AdminUser {
  id: number
  username: string
  display_name: string
  email: string | null
  role_code: string
  team: string | null
  phone: string | null
  is_active: boolean
  must_change_password: boolean
  locked_until: string | null
  last_login_at: string | null
  created_at: string
}

export interface SettingSpec {
  kind: 'bool' | 'int' | 'date' | 'fields' | 'ext_list' | 'aliases'
  label: string
  min?: number
  max?: number
  unit?: string
  choices?: { value: string; label: string }[]
}

export interface SystemSettingRow {
  key: string
  value: unknown
  category: string
  description: string | null
  is_secret: boolean
  /** 한 번도 바꾸지 않아 DB 에 행이 없으면 null(기본값) */
  updated_at: string | null
  spec: SettingSpec | null
}

export interface BackupStatus {
  backup_dir: string
  files: { name: string; size: number; modified_at: string }[]
  latest_at: string | null
  hours_since_latest: number | null
  stale: boolean
  database: string
  attachments: { count: number; bytes: number }
}

export interface ShiftInput { code: string; name: string; start_time: string; end_time: string; sort_order?: number }

// ------------------------------------------------------------------ 댓글 · 첨부

export interface HandoverComment {
  id: number
  handover_id: number
  body: string
  author_id: number | null
  author: string | null
  created_at: string
  is_edited: boolean
  edited_at: string | null
  can_edit: boolean
  can_delete: boolean
}

export type EntityType = 'HANDOVER' | 'TASK' | 'KNOWLEDGE'

export interface AttachmentRow {
  id: number
  entity_type: EntityType
  entity_id: number
  name: string
  size: number
  mime: string | null
  sha256: string | null
  scan_status: 'NOT_SCANNED' | 'CLEAN'
  uploaded_by: string | null
  created_at: string
  can_delete: boolean
  /** 화면에서 바로 미리 볼 수 있는 그림인가(서버가 파일 내용으로 판단) */
  is_image: boolean
}

// ------------------------------------------------------------------ 통계

export interface StatsSummary {
  start: string
  end: string
  total: number
  by_company: { company: string; total: number; open: number; closed: number }[]
  by_status: { code: string; name: string; category: string; count: number }[]
  by_month: { month: string; count: number }[]
  ack: { items: number; acked: number; rate: number | null; median_minutes: number | null
         avg_minutes: number | null; pending_now: number }
  overdue: { handovers: number; tasks: number }
  tasks: { created: number; completed: number; median_hours: number | null }
}

export const adminApi = {
  auditCatalog: () => api.get<AuditCatalog>('/audit/catalog'),
  auditSearch: (q: AuditQuery) => api.post<{ items: AuditRow[]; total: number; page: number; size: number }>('/audit/search', q),
  auditExport: (q: AuditQuery) => api.post<{ download_token: string; file_name: string; rows: number }>('/audit/export', q),

  users: (q = '', role = '', active: '' | 'true' | 'false' = '') =>
    api.get<Page<AdminUser>>(`/users?size=200&q=${encodeURIComponent(q)}${role ? `&role=${role}` : ''}${active ? `&active=${active}` : ''}`),
  roles: () => api.get<{ code: string; name: string; description: string | null }[]>('/roles'),
  createUser: (body: { username: string; display_name: string; password: string; role_code: string; team?: string | null; must_change_password?: boolean }) =>
    api.post<AdminUser>('/users', body),
  updateUser: (id: number, body: Partial<Pick<AdminUser, 'display_name' | 'email' | 'team' | 'phone' | 'role_code' | 'is_active'>>) =>
    api.patch<AdminUser>(`/users/${id}`, body),
  resetPassword: (id: number) => api.post<{ username: string; temporary_password: string }>(`/users/${id}/reset-password`),

  statuses: () => api.get<HandoverStatus[]>('/statuses'),
  upsertStatus: (body: Omit<HandoverStatus, 'is_system'>) => api.post<HandoverStatus>('/statuses', body),
  deactivateStatus: (code: string) => api.delete<void>(`/statuses/${code}`),
  companies: async () => {
    const [on, off] = await Promise.all([api.get<Company[]>('/companies?active=true'), api.get<Company[]>('/companies?active=false')])
    return [...on, ...off]
  },
  createCompany: (body: { name: string; code?: string | null; short_name?: string | null; sort_order?: number }) =>
    api.post<Company>('/companies', body),
  updateCompany: (id: number, body: Partial<Pick<Company, 'name' | 'code' | 'short_name' | 'sort_order' | 'is_active'>>) =>
    api.patch<Company>(`/companies/${id}`, body),
  shifts: () => api.get<Shift[]>('/shifts?include_inactive=true'),
  replaceShifts: (rows: ShiftInput[]) => api.put<Shift[]>('/shifts', rows),

  settings: () => api.get<SystemSettingRow[]>('/settings'),
  updateSetting: (key: string, value: unknown) => api.patch<{ key: string; value: unknown }>(`/settings/${key}`, { value }),
  backups: () => api.get<BackupStatus>('/backups'),

  comments: (handoverId: number) => api.get<HandoverComment[]>(`/handovers/${handoverId}/comments`),
  addComment: (handoverId: number, body: string) => api.post<HandoverComment>(`/handovers/${handoverId}/comments`, { body }),
  editComment: (id: number, body: string) => api.patch<HandoverComment>(`/handover-comments/${id}`, { body }),
  deleteComment: (id: number) => api.delete<void>(`/handover-comments/${id}`),

  attachments: (entityType: EntityType, entityId: number) =>
    api.get<AttachmentRow[]>(`/attachments?entity_type=${entityType}&entity_id=${entityId}`),
  uploadAttachment: (entityType: EntityType, entityId: number, file: File) => {
    const form = new FormData()
    form.append('entity_type', entityType)
    form.append('entity_id', String(entityId))
    form.append('file', file)
    return upload<AttachmentRow>('/attachments', form)
  },
  deleteAttachment: (id: number) => api.delete<void>(`/attachments/${id}`),
  attachmentUrl: (id: number) => `/api/v1/attachments/${id}/download`,
  attachmentPreviewUrl: (id: number) => `/api/v1/attachments/${id}/preview`,

  stats: (start: string, end: string) => api.get<StatsSummary>(`/stats/summary?start=${start}&end=${end}`),
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
