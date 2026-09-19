/** 통합검색(Ctrl+K 팔레트 · /search) — 인수인계 · 할일 · 일정을 한 번에. */
import { api } from '@/services/api/client'

export type HitType = 'handover' | 'task' | 'schedule'

export interface GlobalHit {
  type: HitType
  id: number
  title: string
  snippet: string | null
  company: string | null
  date: string | null
  /** 걸린 칸: 제목 · 내용 · 비고 · 관계사 · 전달자 · 담당자 · 확인자 · 태그 */
  matched: string[]
}

export interface GlobalSearchResult {
  q: string
  hits: GlobalHit[]
  totals: Partial<Record<HitType, number>>
}

export const searchApi = {
  global: (q: string, limit = 8, scope?: HitType[]) =>
    api.post<GlobalSearchResult>('/search/global', { q, limit, ...(scope ? { scope } : {}) }),
}

export const HIT_LABEL: Record<HitType, string> = { handover: '인수인계', task: '할일', schedule: '일정' }

/** 결과를 누르면 여는 곳 — 각 화면이 ?id= 로 상세를 연다. */
export function hitHref(hit: Pick<GlobalHit, 'type' | 'id'>): string {
  if (hit.type === 'task') return `/tasks?id=${hit.id}`
  if (hit.type === 'schedule') return `/schedules?id=${hit.id}`
  return `/handovers?id=${hit.id}`
}

/** '모두 보기' — 같은 검색어로 각 목록을 연다(일정은 목록 화면이 없어 통합검색 화면에서 끝난다). */
export function listHref(type: HitType, q: string): string | null {
  const term = encodeURIComponent(q)
  if (type === 'handover') return `/handovers?q=${term}`
  if (type === 'task') return `/tasks?q=${term}&closed=1`
  return null
}
