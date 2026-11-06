import { api } from './client'

export type KnowledgeCategory = '운영 절차' | '탐지·분석' | '비상 대응' | '장비·솔루션' | '점검 체크리스트' | '참고 자료'

export interface KnowledgeArticle {
  id: number
  category: KnowledgeCategory
  title: string
  body: string
  visibility: 'ALL' | 'GROUPS'
  group_ids: number[]
  is_pinned: boolean
  review_due: string | null
  version_no: number
  created_by: number
  updated_by: number | null
  created_at: string
  updated_at: string
  can_edit: boolean
}

export interface KnowledgeInput {
  category: KnowledgeCategory
  title: string
  body: string
  visibility: 'ALL' | 'GROUPS'
  group_ids: number[]
  is_pinned: boolean
  review_due: string | null
  version_no?: number
}

export const CATEGORIES: KnowledgeCategory[] = [
  '운영 절차', '탐지·분석', '비상 대응', '장비·솔루션', '점검 체크리스트', '참고 자료',
]

export const knowledgeApi = {
  list: (q = '', category = '', offset = 0) => {
    const p = new URLSearchParams({ offset: String(offset), limit: '50' })
    if (q) p.set('q', q)
    if (category) p.set('category', category)
    return api.get<KnowledgeArticle[]>(`/knowledge?${p}`)
  },
  get: (id: number) => api.get<KnowledgeArticle>(`/knowledge/${id}`),
  create: (body: KnowledgeInput) => api.post<KnowledgeArticle>('/knowledge', body),
  update: (id: number, body: KnowledgeInput) => api.patch<KnowledgeArticle>(`/knowledge/${id}`, body),
  remove: (id: number) => api.delete<void>(`/knowledge/${id}`),
}
