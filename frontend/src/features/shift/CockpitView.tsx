/**
 * Shift Cockpit (UI_STRUCTURE §5, FR-C-01) — 이번 근무의 6영역을 보고 넘길 것을 고른다.
 *
 * 각 영역의 숫자는 인수인계 목록과 같은 조건으로 센다. '목록으로 보기'를 누르면 같은
 * 조건이 그대로 열린다.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ExternalLink } from 'lucide-react'
import BasketPanel from '@/features/shift/BasketPanel'
import { shiftApi } from '@/services/api/shift'
import type { SearchRequest } from '@/types/handover'

const TONE: Record<string, string> = {
  need_ack: 'text-state-check', important: 'text-state-high', overdue: 'text-state-urgent',
}

function listUrl(req: SearchRequest): string {
  const params = new URLSearchParams()
  if (req.quick?.length) params.set('quick', req.quick.join(','))
  if (req.filters?.length) params.set('f', JSON.stringify(req.filters))
  if (req.sort?.length) params.set('sort', req.sort.map((s) => `${s.field}:${s.dir}`).join(','))
  return `/handovers?${params.toString()}`
}

function hhmm(iso: string): string {
  return new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function CockpitView() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [area, setArea] = useState('in_progress')
  const [picked, setPicked] = useState<Set<number>>(new Set())

  const { data } = useQuery({ queryKey: ['cockpit'], queryFn: shiftApi.cockpit, refetchInterval: 60_000 })
  const add = useMutation({
    mutationFn: () => shiftApi.addItems([...picked]),
    onSuccess: () => {
      setPicked(new Set())
      qc.invalidateQueries({ queryKey: ['basket'] })
      qc.invalidateQueries({ queryKey: ['cockpit'] })
    },
  })

  const current = data?.areas[area]
  const inBasket = useMemo(() => new Set(data?.basket_handover_ids ?? []), [data])
  const rows = current?.items ?? []

  const toggle = (id: number) => {
    const next = new Set(picked)
    next.has(id) ? next.delete(id) : next.add(id)
    setPicked(next)
  }

  const next = data?.next_window
  const nextLabel = next ? `${next.name} ${hhmm(next.start_at)}~` : '다음 교대'

  return (
    <div className="flex-1 flex flex-col lg:flex-row min-h-0 max-lg:overflow-y-auto">
      <div className="lg:flex-1 min-w-0 flex flex-col min-h-[460px] lg:min-h-0 p-3 gap-2">
        {data && (
          <p className="text-ink-muted">
            <b className="text-ink">{data.window.shift_date} {data.window.name}</b>
            {' '}({hhmm(data.window.start_at)}~{hhmm(data.window.end_at)})
            <ArrowRight size={12} className="inline mx-1" />
            다음 {nextLabel}
          </p>
        )}

        <div className="grid grid-cols-3 gap-2" role="tablist" aria-label="Cockpit 영역">
          {Object.entries(data?.areas ?? {}).map(([key, a]) => (
            <button key={key} role="tab" aria-selected={area === key}
                    onClick={() => { setArea(key); setPicked(new Set()) }}
                    className={`card px-3 py-2 text-left ${area === key ? 'border-brand ring-1 ring-brand' : 'hover:border-brand/50'}`}>
              <div className="text-xs text-ink-faint">{a.label}</div>
              <div className={`text-lg font-semibold tabular-nums ${a.total ? (TONE[key] ?? 'text-ink') : 'text-ink-faint'}`}>
                {a.total.toLocaleString()}
              </div>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-medium">{current?.label}</h2>
          {current && current.total > rows.length && (
            <span className="text-sm text-ink-faint">상위 {rows.length}건 표시</span>
          )}
          <span className="flex-1" />
          {current && (
            <button className="btn btn-sm" onClick={() => navigate(listUrl(current.request))}>
              <ExternalLink size={11} /> 목록으로 보기
            </button>
          )}
          <button className="btn btn-sm btn-primary" disabled={!picked.size || add.isPending}
                  onClick={() => add.mutate()}>
            선택 {picked.size}건 인계 대상에 추가 <ArrowRight size={11} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-auto border border-surface-border rounded">
          <table className="w-full text-base whitespace-nowrap">
            <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
              <tr>
                <th className="w-8 px-2 py-1">
                  <input type="checkbox" aria-label="전체 선택"
                         checked={rows.length > 0 && rows.every((r) => picked.has(r.id) || inBasket.has(r.id))}
                         onChange={(e) => setPicked(e.target.checked
                           ? new Set(rows.filter((r) => !inBasket.has(r.id)).map((r) => r.id)) : new Set())} />
                </th>
                <th className="text-left font-medium px-2 py-1">번호</th>
                <th className="text-left font-medium px-2 py-1">관계사</th>
                <th className="text-left font-medium px-2 py-1">제목</th>
                <th className="text-left font-medium px-2 py-1">상태</th>
                <th className="text-left font-medium px-2 py-1">담당자</th>
                <th className="text-left font-medium px-2 py-1">수행일</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={7} className="py-6 text-center text-ink-faint">해당하는 인수인계가 없습니다.</td></tr>
              )}
              {rows.map((r) => {
                const already = inBasket.has(r.id)
                return (
                  <tr key={r.id} className="border-t border-surface-border/60 hover:bg-surface-sunken">
                    <td className="px-2 py-1 text-center">
                      {already ? <span className="text-xs text-state-done" title="이미 Basket 에 있음">담김</span> : (
                        <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)}
                               aria-label={`#${r.id} 선택`} />
                      )}
                    </td>
                    <td className="px-2 py-1 tabular-nums text-ink-faint">#{r.id}</td>
                    <td className="px-2 py-1">{r.company?.short_name ?? r.company?.name}</td>
                    <td className="px-2 py-1 max-w-[360px]">
                      <button className="truncate text-left hover:underline max-w-full"
                              onClick={() => navigate(`/handovers?id=${r.id}`)} title={r.title}>
                        {r.priority?.code === 'URGENT' && <span className="text-state-urgent mr-1">⛔</span>}
                        {r.is_important && <span className="text-state-high mr-1" title="중요">★</span>}
                        {r.title}
                      </button>
                    </td>
                    <td className="px-2 py-1">{r.status?.name}</td>
                    <td className="px-2 py-1">{r.assignee?.display_name ?? r.assignee_name_raw ?? '-'}</td>
                    <td className="px-2 py-1 tabular-nums">{r.work_date ?? '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <BasketPanel nextShiftLabel={nextLabel} />
    </div>
  )
}
