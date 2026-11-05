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
}
