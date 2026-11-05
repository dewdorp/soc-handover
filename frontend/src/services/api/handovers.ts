/** 인수인계 · 검색 API. 서버 DSL과 동일한 형태로 주고받는다. */
import { api } from '@/services/api/client'
import type { Page } from '@/types/api'
import type {
  Acknowledgement, FacetValue, HandoverDetail, HandoverListItem, SavedView,
  SearchCapabilities, SearchRequest, TimelineEvent, VersionDetail, VersionDiff,
  VersionSummary,
} from '@/types/handover'

export const handoverApi = {
  search: (body: SearchRequest) =>
    api.post<Page<HandoverListItem>>('/handovers/search', body),

  facets: (field: string, body: SearchRequest, facetQ = '', limit = 200) =>
    api.post<FacetValue[]>('/handovers/facets', { ...body, field, facet_q: facetQ, limit }),

  get: (id: number) => api.get<HandoverDetail>(`/handovers/${id}`),

  asOf: (id: number, at: string) =>
    api.get<{ handover_id: number; version_no: number; data: Record<string, unknown> }>(
      `/handovers/${id}?as_of=${encodeURIComponent(at)}`),

  create: (body: Record<string, unknown>) =>
    api.post<HandoverDetail>('/handovers', body),

  update: (id: number, body: Record<string, unknown>) =>
    api.patch<HandoverDetail>(`/handovers/${id}`, body),

  remove: (id: number, reason: string) =>
    api.delete<HandoverDetail>(`/handovers/${id}`, { reason }),

  undelete: (id: number) => api.post<HandoverDetail>(`/handovers/${id}/undelete`),

  star: (id: number, on: boolean) =>
    on ? api.post<void>(`/handovers/${id}/star`) : api.delete<void>(`/handovers/${id}/star`),

  pin: (id: number, pinned: boolean) =>
    api.post<HandoverDetail>(`/handovers/${id}/pin`, { pinned }),

  /** expectedVersion: 화면이 보여 준 버전. 그 사이에 바뀌었으면 서버가 409(stale_ack) 로 보류한다 */
  acknowledge: (id: number, expectedVersion: number | null, note?: string) =>
    api.post<Acknowledgement>(`/handovers/${id}/acknowledge`,
      { expected_version: expectedVersion, note: note ?? null }),

  versions: (id: number) => api.get<VersionSummary[]>(`/handovers/${id}/versions`),

  version: (id: number, no: number) =>
    api.get<VersionDetail>(`/handovers/${id}/versions/${no}`),

  diff: (id: number, from: number, to: number) =>
    api.get<VersionDiff>(`/handovers/${id}/versions/diff?from=${from}&to=${to}`),

  restore: (id: number, no: number, expectedVersion: number, reason: string) =>
    api.post<HandoverDetail>(`/handovers/${id}/versions/${no}/restore`, {
      expected_version: expectedVersion, change_reason: reason,
    }),

  timeline: (id: number) => api.get<TimelineEvent[]>(`/handovers/${id}/timeline`),

  markViewed: (id: number) => api.post<void>(`/handovers/${id}/view`),
}

export const searchApi = {
  capabilities: () => api.get<SearchCapabilities>('/search/fields'),
}

export const savedViewApi = {
  list: (target = 'HANDOVER') => api.get<SavedView[]>(`/saved-views?target=${target}`),
  default: (target = 'HANDOVER') => api.get<SavedView | null>(`/saved-views/default?target=${target}`),
  create: (body: Record<string, unknown>) => api.post<SavedView>('/saved-views', body),
  update: (id: number, body: Record<string, unknown>) =>
    api.patch<SavedView>(`/saved-views/${id}`, body),
  remove: (id: number) => api.delete<void>(`/saved-views/${id}`),
  makeDefault: (id: number) => api.post<SavedView>(`/saved-views/${id}/default`),
}
