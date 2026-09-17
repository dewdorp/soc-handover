/** 기준 정보 API (관계사·상태·중요도·교대·태그·사용자 조회). */
import { api } from '@/services/api/client'
import type { Company, HandoverStatus, Priority, Shift, UserBrief } from '@/types/api'

export const referenceApi = {
  companies: () => api.get<Company[]>('/companies'),
  statuses: () => api.get<HandoverStatus[]>('/statuses?active=true'),
  priorities: () => api.get<Priority[]>('/priorities'),
  shifts: () => api.get<Shift[]>('/shifts'),
  tags: (q = '') => api.get<{ id: number; name: string; usage_count: number }[]>(
    `/tags?q=${encodeURIComponent(q)}`),
  userLookup: (q = '') => api.get<UserBrief[]>(`/users/lookup?q=${encodeURIComponent(q)}`),
}
