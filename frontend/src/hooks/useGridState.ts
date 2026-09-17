/**
 * 그리드 상태를 URL query 에 직렬화한다(UI_STRUCTURE §3 동작규칙).
 *
 * 이렇게 두면 새로고침해도 보던 화면이 그대로고, 주소를 복사해 옆자리에 보내면
 * 같은 결과를 본다. "어떤 필터였더라"를 다시 만들 필요가 없다.
 *
 * 필터는 DSL 배열이라 그대로 넣으면 주소가 지저분해지므로 f= 하나에 JSON 으로 싣는다.
 */
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Filter, SearchRequest, Sort } from '@/types/handover'

export type Density = 'compact' | 'normal' | 'comfortable'

export interface GridState {
  q: string
  filters: Filter[]
  sort: Sort[]
  quick: string[]
  page: number
  size: number
  density: Density
  hidden: string[]
  includeDeleted: boolean
  selectedId: number | null
}

const DEFAULTS: GridState = {
  q: '', filters: [], sort: [{ field: 'registered_date', dir: 'desc' }], quick: [],
  page: 1, size: 50, density: 'compact', hidden: [], includeDeleted: false, selectedId: null,
}

function parseJson<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) || typeof parsed === 'object' ? (parsed as T) : fallback
  } catch {
    return fallback // 손상된 링크로 화면이 죽지 않게 한다
  }
}

function parseSort(raw: string | null): Sort[] {
  if (!raw) return DEFAULTS.sort
  const out: Sort[] = []
  for (const token of raw.split(',')) {
    const [field, dir] = token.split(':')
    if (field) out.push({ field, dir: dir === 'desc' ? 'desc' : 'asc' })
  }
  return out.length ? out : DEFAULTS.sort
}

function serializeSort(sort: Sort[]): string {
  return sort.map((s) => `${s.field}:${s.dir}`).join(',')
}

export function useGridState() {
  const [params, setParams] = useSearchParams()

  const state = useMemo<GridState>(() => ({
    q: params.get('q') ?? '',
    filters: parseJson<Filter[]>(params.get('f'), []),
    sort: parseSort(params.get('sort')),
    quick: params.get('quick')?.split(',').filter(Boolean) ?? [],
    page: Number(params.get('page')) || 1,
    size: Number(params.get('size')) || DEFAULTS.size,
    density: (params.get('density') as Density) || DEFAULTS.density,
    hidden: params.get('hide')?.split(',').filter(Boolean) ?? [],
    includeDeleted: params.get('deleted') === '1',
    selectedId: params.get('id') ? Number(params.get('id')) : null,
  }), [params])

  const patch = useCallback((changes: Partial<GridState>, options?: { keepPage?: boolean }) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      const merged = { ...changes }
      // 조건이 바뀌면 1페이지로 돌아간다. 3페이지를 보다 필터를 바꿨는데 빈 화면이 뜨면 안 된다.
      const changesConditions = ['q', 'filters', 'quick', 'size', 'includeDeleted']
        .some((k) => k in changes)
      if (changesConditions && !options?.keepPage && !('page' in changes)) merged.page = 1

      const put = (key: string, value: string, isDefault: boolean) => {
        if (isDefault) next.delete(key)
        else next.set(key, value)
      }

      if ('q' in merged) put('q', merged.q ?? '', !merged.q)
      if ('filters' in merged) {
        const list = merged.filters ?? []
        put('f', JSON.stringify(list), list.length === 0)
      }
      if ('sort' in merged) {
        const s = serializeSort(merged.sort ?? [])
        put('sort', s, s === serializeSort(DEFAULTS.sort))
      }
      if ('quick' in merged) {
        const list = merged.quick ?? []
        put('quick', list.join(','), list.length === 0)
      }
      if ('page' in merged) put('page', String(merged.page), merged.page === 1)
      if ('size' in merged) put('size', String(merged.size), merged.size === DEFAULTS.size)
      if ('density' in merged) {
        put('density', merged.density ?? 'compact', merged.density === DEFAULTS.density)
      }
      if ('hidden' in merged) {
        const list = merged.hidden ?? []
        put('hide', list.join(','), list.length === 0)
      }
      if ('includeDeleted' in merged) put('deleted', '1', !merged.includeDeleted)
      if ('selectedId' in merged) {
        put('id', String(merged.selectedId), merged.selectedId == null)
      }
      return next
    }, { replace: true })
  }, [setParams])

  /** 서버로 보낼 DSL. 화면 상태(밀도·숨김 컬럼)는 검색 조건이 아니므로 뺀다. */
  const request = useMemo<SearchRequest>(() => ({
    q: state.q || null,
    filters: state.filters,
    sort: state.sort,
    quick: state.quick,
    page: state.page,
    size: state.size,
    include_deleted: state.includeDeleted,
  }), [state])

  const reset = useCallback(() => {
    patch({ q: '', filters: [], quick: [], page: 1, includeDeleted: false })
  }, [patch])

  const setFilter = useCallback((field: string, replacement: Filter[]) => {
    const others = state.filters.filter((f) => f.field !== field)
    patch({ filters: [...others, ...replacement] })
  }, [state.filters, patch])

  const removeFilter = useCallback((index: number) => {
    patch({ filters: state.filters.filter((_, i) => i !== index) })
  }, [state.filters, patch])

  const toggleQuick = useCallback((token: string) => {
    const on = state.quick.includes(token)
    patch({ quick: on ? state.quick.filter((t) => t !== token) : [...state.quick, token] })
  }, [state.quick, patch])

  const toggleSort = useCallback((field: string, additive: boolean) => {
    const existing = state.sort.find((s) => s.field === field)
    const flipped: Sort = { field, dir: existing?.dir === 'asc' ? 'desc' : 'asc' }
    if (!additive) {
      patch({ sort: [flipped] })
      return
    }
    const others = state.sort.filter((s) => s.field !== field)
    patch({ sort: [...others, flipped] })
  }, [state.sort, patch])

  return { state, request, patch, reset, setFilter, removeFilter, toggleQuick, toggleSort }
}
