/**
 * 인수인계 목록 — 가장 중요한 화면 (UI_STRUCTURE §3).
 *
 * 그리드 상태는 전부 URL 에 있다(useGridState). 주소를 복사해 보내면 같은 화면이 뜨고,
 * 새로고침해도 보던 조건이 유지된다.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, ChevronLeft, ChevronRight, Download, Plus, RotateCcw, Search, X } from 'lucide-react'
import CreateHandoverDialog from '@/features/handovers/CreateHandoverDialog'
import ExportDialog from '@/features/handovers/ExportDialog'
import HandoverDrawer from '@/features/handovers/HandoverDrawer'
import HandoverGrid from '@/features/handovers/HandoverGrid'
import { fieldLabel } from '@/features/handovers/VersionHistory'
import { useGridState, type Density } from '@/hooks/useGridState'
import { handoverApi, savedViewApi, searchApi } from '@/services/api/handovers'
import { referenceApi } from '@/services/api/reference'
import type { Filter, HandoverListItem } from '@/types/handover'

const OP_LABEL: Record<string, string> = {
  eq: '=', ne: '≠', in: '', not_in: '제외', contains: '포함', not_contains: '미포함',
  starts_with: '시작', ends_with: '끝', between: '', gte: '≥', lte: '≤',
  is_null: '비어있음', is_not_null: '있음', any_of_tags: '',
}

const DENSITIES: { key: Density; label: string }[] = [
  { key: 'compact', label: '좁게' }, { key: 'normal', label: '보통' },
  { key: 'comfortable', label: '넓게' },
]

export default function HandoverListPage() {
  const qc = useQueryClient()
  const grid = useGridState()
  const [draftQ, setDraftQ] = useState(grid.state.q)
  const [creating, setCreating] = useState(false)
  const [exporting, setExporting] = useState(false)

  const { data: caps } = useQuery({
    queryKey: ['search-fields'], queryFn: searchApi.capabilities, staleTime: 10 * 60_000,
  })
  const { data: companies } = useQuery({
    queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 5 * 60_000,
  })
  const { data: statuses } = useQuery({
    queryKey: ['statuses'], queryFn: referenceApi.statuses, staleTime: 5 * 60_000,
  })
  const { data: priorities } = useQuery({
    queryKey: ['priorities'], queryFn: referenceApi.priorities, staleTime: 5 * 60_000,
  })
  const { data: views } = useQuery({
    queryKey: ['saved-views'], queryFn: () => savedViewApi.list('HANDOVER'),
  })

  const { data: page, isLoading, isFetching } = useQuery({
    queryKey: ['handovers', grid.request],
    queryFn: () => handoverApi.search(grid.request),
    placeholderData: (prev) => prev,
  })

  const fields = useMemo(
    () => new Map((caps?.fields ?? []).map((f) => [f.name, f])), [caps])

  /**
   * Chip 에 IN_PROGRESS 같은 내부 코드를 그대로 보여주면 안 된다.
   * 기준정보를 이미 받아 두었으므로 사람이 읽는 이름으로 바꿔 준다.
   */
  const labelOf = useMemo(() => {
    const table = new Map<string, string>()
    companies?.forEach((c) => table.set(`company_id:${c.id}`, c.name))
    statuses?.forEach((s) => table.set(`status_code:${s.code}`, s.name))
    priorities?.forEach((p) => table.set(`priority_code:${p.code}`, p.name))
    return (field: string, value: unknown) =>
      table.get(`${field}:${String(value)}`) ?? String(value)
  }, [companies, statuses, priorities])

  const star = useMutation({
    mutationFn: (row: HandoverListItem) => handoverApi.star(row.id, !row.is_starred),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['handovers'] }),
  })

  const saveView = useMutation({
    mutationFn: (name: string) => savedViewApi.create({
      name, target: 'HANDOVER', scope: 'PERSONAL',
      state: { q: grid.state.q, filters: grid.state.filters, sort: grid.state.sort,
               quick: grid.state.quick, density: grid.state.density, hidden: grid.state.hidden },
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-views'] }),
  })

  const applyView = (state: Record<string, unknown>) => {
    grid.patch({
      q: (state.q as string) ?? '',
      filters: (state.filters as Filter[]) ?? [],
      sort: (state.sort as never) ?? undefined,
      quick: (state.quick as string[]) ?? [],
      density: (state.density as Density) ?? 'compact',
      hidden: (state.hidden as string[]) ?? [],
      page: 1,
    })
    setDraftQ((state.q as string) ?? '')
  }

  const total = page?.total ?? 0
  const totalAll = page?.total_all ?? 0
  const lastPage = Math.max(1, Math.ceil(total / grid.state.size))
  const hasConditions = Boolean(grid.state.q || grid.state.filters.length || grid.state.quick.length)

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        {/* 상단 */}
        <div className="px-3 pt-2 pb-1.5 space-y-1.5">
          <div className="flex items-center gap-2">
            <h1 className="text-md font-medium">인수인계</h1>
            <span className="flex-1" />
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              <Plus size={12} /> 인수인계
            </button>
            <button className="btn" onClick={() => setExporting(true)}>
              <Download size={12} /> Export
            </button>
            <button className="btn" onClick={() => {
              const name = window.prompt('현재 조건을 저장할 이름을 입력하십시오.')
              if (name?.trim()) saveView.mutate(name.trim())
            }}><Bookmark size={12} /> 보기 저장</button>
          </div>

          <form className="relative" onSubmit={(e) => { e.preventDefault(); grid.patch({ q: draftQ }) }}>
            <Search size={13} className="absolute left-2 top-2 text-ink-faint" />
            <input className="input w-full pl-7" value={draftQ}
                   onChange={(e) => setDraftQ(e.target.value)}
                   placeholder="통합 검색 (제목·내용·비고·관계사·인명·태그)" />
            {draftQ && (
              <button type="button" aria-label="검색어 지우기"
                      className="absolute right-2 top-1.5 text-ink-faint hover:text-ink"
                      onClick={() => { setDraftQ(''); grid.patch({ q: '' }) }}><X size={13} /></button>
            )}
          </form>

          {/* Quick Filter + 밀도 */}
          <div className="flex items-center gap-1 flex-wrap">
            {(caps?.quick_filters ?? []).map((qf) => {
              const on = grid.state.quick.includes(qf.token)
              return (
                <button key={qf.token} onClick={() => grid.toggleQuick(qf.token)}
                        aria-pressed={on}
                        className={`btn btn-sm ${on ? 'btn-primary' : ''}`}>{qf.label}</button>
              )
            })}
            <span className="flex-1" />
            <div className="flex items-center gap-0.5" role="group" aria-label="행 밀도">
              {DENSITIES.map((d) => (
                <button key={d.key} onClick={() => grid.patch({ density: d.key })}
                        aria-pressed={grid.state.density === d.key}
                        className={`btn btn-sm ${grid.state.density === d.key ? 'btn-primary' : ''}`}>
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {/* 저장된 보기 */}
          {(views?.length ?? 0) > 0 && (
            <div className="flex items-center gap-1 flex-wrap text-sm">
              {views!.map((v) => (
                <button key={v.id} className="chip hover:bg-surface"
                        onClick={() => applyView(v.state)}
                        title={v.scope === 'SHARED' ? '공용 보기' : '내 보기'}>
                  {v.scope === 'SHARED' ? '👥' : '⭐'} {v.name}
                </button>
              ))}
            </div>
          )}

          {/* 적용 필터 Chip */}
          {hasConditions && (
            <div className="flex items-center gap-1 flex-wrap border border-surface-border
                            rounded bg-surface-sunken px-2 py-1">
              <span className="text-ink-muted text-sm">적용 필터</span>
              {grid.state.q && (
                <Chip label={`검색: ${grid.state.q}`}
                      onRemove={() => { setDraftQ(''); grid.patch({ q: '' }) }} />
              )}
              {grid.state.quick.map((token) => (
                <Chip key={token}
                      label={caps?.quick_filters.find((q) => q.token === token)?.label ?? token}
                      onRemove={() => grid.toggleQuick(token)} />
              ))}
              {grid.state.filters.map((f, i) => (
                <Chip key={`${f.field}-${i}`} label={chipLabel(f, labelOf)}
                      onRemove={() => grid.removeFilter(i)} />
              ))}
              <span className="flex-1" />
              <button className="btn btn-sm" onClick={() => { setDraftQ(''); grid.reset() }}>
                <RotateCcw size={11} /> 전체 초기화
              </button>
            </div>
          )}

          {/* 건수 · 페이지 */}
          <div className="flex items-center gap-2 text-ink-muted">
            <span>
              전체 <b className="text-ink tabular-nums">{totalAll.toLocaleString()}</b>건
              {' · '}현재 검색결과 <b className="text-ink tabular-nums">{total.toLocaleString()}</b>건
            </span>
            {isFetching && <span className="text-ink-faint">갱신 중…</span>}
            <span className="flex-1" />
            <select className="input h-6 text-sm" value={grid.state.size}
                    onChange={(e) => grid.patch({ size: Number(e.target.value) })}
                    aria-label="페이지당 행 수">
              {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <div className="flex items-center gap-1">
              <button className="btn btn-sm" disabled={grid.state.page <= 1}
                      onClick={() => grid.patch({ page: grid.state.page - 1 }, { keepPage: true })}
                      aria-label="이전 페이지"><ChevronLeft size={12} /></button>
              <span className="tabular-nums">{grid.state.page} / {lastPage}</span>
              <button className="btn btn-sm" disabled={!page?.has_next}
                      onClick={() => grid.patch({ page: grid.state.page + 1 }, { keepPage: true })}
                      aria-label="다음 페이지"><ChevronRight size={12} /></button>
            </div>
          </div>
        </div>

        <HandoverGrid rows={page?.items ?? []} fields={fields} state={grid.state}
                      request={grid.request} selectedId={grid.state.selectedId}
                      isLoading={isLoading}
                      onSelect={(id) => grid.patch({ selectedId: id }, { keepPage: true })}
                      onToggleStar={(row) => star.mutate(row)}
                      onSort={grid.toggleSort} onSetFilter={grid.setFilter} />
      </div>

      {grid.state.selectedId != null && (
        <HandoverDrawer handoverId={grid.state.selectedId}
                        companies={companies ?? []} statuses={statuses ?? []}
                        priorities={priorities ?? []}
                        onClose={() => grid.patch({ selectedId: null }, { keepPage: true })} />
      )}

      {exporting && (
        <ExportDialog request={grid.request} total={total} onClose={() => setExporting(false)} />
      )}

      {creating && (
        <CreateHandoverDialog companies={companies ?? []} statuses={statuses ?? []}
                              priorities={priorities ?? []}
                              onClose={() => setCreating(false)}
                              onCreated={(id) => {
                                setCreating(false)
                                qc.invalidateQueries({ queryKey: ['handovers'] })
                                grid.patch({ selectedId: id }, { keepPage: true })
                              }} />
      )}
    </div>
  )
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="chip bg-surface">
      {label}
      <button onClick={onRemove} aria-label={`${label} 필터 제거`}
              className="text-ink-faint hover:text-state-urgent"><X size={11} /></button>
    </span>
  )
}

const DATE_TOKEN_LABEL: Record<string, string> = {
  TODAY: '오늘', YESTERDAY: '어제', THIS_WEEK: '이번주', LAST_WEEK: '지난주',
  THIS_MONTH: '이번달', LAST_MONTH: '지난달', LAST_7_DAYS: '최근7일',
  LAST_30_DAYS: '최근30일', THIS_YEAR: '올해', LAST_YEAR: '작년',
}

function chipLabel(f: Filter, labelOf: (field: string, value: unknown) => string): string {
  const name = fieldLabel(f.field)
  const op = OP_LABEL[f.op] ?? f.op
  if (f.op === 'is_null' || f.op === 'is_not_null') return `${name} ${op}`

  const render = (v: unknown) => DATE_TOKEN_LABEL[String(v)] ?? labelOf(f.field, v)
  const value = Array.isArray(f.value)
    ? (f.value as unknown[]).map(render).join(f.op === 'between' ? ' ~ ' : ', ')
    : render(f.value ?? '')
  const shown = value.length > 24 ? `${value.slice(0, 24)}…` : value
  return op ? `${name} ${op} ${shown}` : `${name}: ${shown}`
}
