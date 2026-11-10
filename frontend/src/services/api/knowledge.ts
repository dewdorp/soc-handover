/**
 * 운영 지식 API.
 *
 * 열람 판정은 전부 서버가 한다. 여기 있는 함수는 '볼 수 있는 것만' 돌려받는다 —
 * 볼 수 없는 문서는 목록에도 없고, 번호로 직접 불러도 404 다.
 */
import { api } from './client'

export type KnowledgeCategory = '운영 절차' | '탐지·분석' | '비상 대응' | '장비·솔루션' | '점검 체크리스트' | '참고 자료'

export interface KnowledgeArticle {
  id: number
  category: KnowledgeCategory
  title: string
  body: string
  visibility: 'ALL' | 'GROUPS'
  group_ids: number[]
  group_names: string[]
  tags: string[]
  is_pinned: boolean
  review_due: string | null
  review_overdue: boolean
  version_no: number
  created_by: number
  created_by_name: string | null
  updated_by: number | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
  can_edit: boolean
}

export interface KnowledgeInput {
  category: KnowledgeCategory
  title: string
  body: string
  visibility: 'ALL' | 'GROUPS'
  group_ids: number[]
  tags: string[]
  is_pinned: boolean
  review_due: string | null
  change_note?: string | null
  version_no?: number
}

export interface KnowledgeRevision {
  version_no: number
  title: string
  category: string
  visibility: string
  tags: string
  change_note: string | null
  changed_by: number | null
  changed_by_name: string | null
  changed_at: string
  body_chars: number
}

export interface KnowledgeRevisionBody {
  version_no: number
  title: string
  category: string
  body: string
  tags: string
  visibility: string
  change_note: string | null
  changed_at: string
}

export interface KnowledgeLink {
  handover_id: number
  title: string
  status_code: string | null
  created_at: string | null
}

export interface KnowledgeSuggestion {
  id: number
  title: string
  category: string
  score: number
}

export interface KnowledgeListQuery {
  q?: string
  category?: string
  tag?: string
  reviewDueOnly?: boolean
  offset?: number
}

export const CATEGORIES: KnowledgeCategory[] = [
  '운영 절차', '탐지·분석', '비상 대응', '장비·솔루션', '점검 체크리스트', '참고 자료',
]

const P = '/knowledge'

export const knowledgeApi = {
  list: ({ q = '', category = '', tag = '', reviewDueOnly = false, offset = 0 }: KnowledgeListQuery = {}) => {
    const p = new URLSearchParams({ offset: String(offset), limit: '50' })
    if (q) p.set('q', q)
    if (category) p.set('category', category)
    if (tag) p.set('tag', tag)
    if (reviewDueOnly) p.set('review_due_only', 'true')
    return api.get<KnowledgeArticle[]>(`${P}?${p}`)
  },
  get: (id: number) => api.get<KnowledgeArticle>(`${P}/${id}`),
  create: (body: KnowledgeInput) => api.post<KnowledgeArticle>(P, body),
  update: (id: number, body: KnowledgeInput) => api.patch<KnowledgeArticle>(`${P}/${id}`, body),
  remove: (id: number) => api.delete<void>(`${P}/${id}`),
  restore: (id: number) => api.post<KnowledgeArticle>(`${P}/${id}/restore`, {}),
  /** 새 문서에 넣을 표준 양식(목적·범위 / 탐지 / 분석 / 조치 / 보고 / 후속 / 관련 문서) */
  template: () => api.get<{ body: string }>(`${P}/template`),

  revisions: (id: number) => api.get<KnowledgeRevision[]>(`${P}/${id}/revisions`),
  revision: (id: number, versionNo: number) =>
    api.get<KnowledgeRevisionBody>(`${P}/${id}/revisions/${versionNo}`),
  restoreRevision: (id: number, versionNo: number) =>
    api.post<KnowledgeArticle>(`${P}/${id}/revisions/${versionNo}/restore`, {}),

  links: (id: number) => api.get<KnowledgeLink[]>(`${P}/${id}/handovers`),
  link: (id: number, handoverId: number) =>
    api.post<KnowledgeLink>(`${P}/${id}/handovers`, { handover_id: handoverId }),
  unlink: (id: number, handoverId: number) =>
    api.delete<void>(`${P}/${id}/handovers/${handoverId}`),

  /** 인수인계 제목에 쓰인 말로 관련 절차를 찾는다(규칙 기반, AI 아님) */
  suggest: (text: string, handoverId?: number) => {
    const p = new URLSearchParams({ text })
    if (handoverId) p.set('handover_id', String(handoverId))
    return api.get<KnowledgeSuggestion[]>(`${P}/suggest?${p}`)
  },
  /** 이 인수인계에 걸어 둔 절차 문서 */
  forHandover: (handoverId: number) =>
    api.get<KnowledgeSuggestion[]>(`${P}/for-handover/${handoverId}`),
}
