/** 열람 그룹 API — 관리(관리자)와 '내 그룹'(모두). */
import { api } from '@/services/api/client'

export interface Group {
  id: number
  code: string | null
  name: string
  description: string | null
  is_active: boolean
  sort_order: number
  member_count: number
  handover_count: number
}

export interface MyGroup {
  id: number
  name: string
  code: string | null
  is_default: boolean
}

export interface GroupMember {
  user_id: number
  username: string
  display_name: string
  role_code: string
  is_active: boolean
  is_default: boolean
}

export interface UnclassifiedSummary {
  group_id: number
  group_name: string
  total: number
  by_company: { company_id: number; company_name: string; count: number }[]
}

/** 저장 전 점검 — '이 공개 범위로 올리면 누가 못 보는가' */
export interface ScopeCheckResult {
  visibility: string
  group_names: string[]
  public: boolean
  outsiders: {
    user_id: number
    display_name: string
    username: string
    role_code: string | null
    my_groups: string[]
  }[]
}

/** 과거 '그룹 미지정' 자료를 전체 공개로 바꾸기 전에 보는 화면 */
export interface PublicMigrationPreview {
  eligible: number
  visible_after: number
  deleted_included: number
  reader_count: number
  confirm_phrase: string
  truncated: boolean
  warnings: string[]
  items: {
    id: number
    title: string
    created_at: string | null
    is_important: boolean
    company: string | null
    author: string | null
  }[]
}

export interface PublicMigrationBatch {
  batch_id: string
  count: number
  converted_at: string | null
  converted_by: number | null
  converted_by_name: string | null
  reverted: number
  revertable: boolean
}

export const groupsApi = {
  mine: () => api.get<MyGroup[]>('/groups/mine'),
  list: (includeInactive = true) =>
    api.get<Group[]>(`/groups?include_inactive=${includeInactive}`),
  create: (body: { name: string; description?: string | null; sort_order?: number }) =>
    api.post<Group>('/groups', body),
  update: (id: number, body: Partial<Pick<Group, 'name' | 'description' | 'sort_order' | 'is_active'>>) =>
    api.patch<Group>(`/groups/${id}`, body),
  members: (id: number) => api.get<GroupMember[]>(`/groups/${id}/members`),
  userGroups: (userId: number) => api.get<MyGroup[]>(`/users/${userId}/groups`),
  setMemberships: (userId: number, groupIds: number[], defaultGroupId: number | null) =>
    api.put<MyGroup[]>(`/users/${userId}/groups`, {
      group_ids: groupIds,
      default_group_id: defaultGroupId,
    }),
  unclassified: () => api.get<UnclassifiedSummary>('/groups/unclassified/summary'),
  move: (body: { to_group_id: number; company_id?: number | null; limit?: number | null }) =>
    api.post<{ moved: number; remaining: number; to_group_id: number }>(
      '/groups/unclassified/move', body),

  /** 저장 전에 '이 범위로는 누가 못 보는가'를 묻는다. 아무것도 바꾸지 않는다. */
  scopeCheck: (body: { visibility?: string | null; group_ids: number[]; user_ids: number[] }) =>
    api.post<ScopeCheckResult>('/groups/scope-check', body),

  publicMigration: {
    preview: (limit = 50) =>
      api.get<PublicMigrationPreview>(`/groups/public-migration?limit=${limit}`),
    batches: () => api.get<PublicMigrationBatch[]>('/groups/public-migration/batches'),
    apply: (confirm: string, backupConfirmed: boolean) =>
      api.post<{ batch_id: string; converted: number }>('/groups/public-migration/apply', {
        confirm, backup_confirmed: backupConfirmed,
      }),
    revert: (batchId: string) =>
      api.post<{ batch_id: string; restored: number; skipped: number }>(
        `/groups/public-migration/batches/${batchId}/revert`, {}),
  },
}
