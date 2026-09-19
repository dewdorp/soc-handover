/**
 * 인계 이력 — 누가 누구에게 무엇을 어느 버전으로 넘겼고, 받는 사람이 확인했는가.
 * (REQUIREMENTS §7: "누가 누구에게 무엇을 전달했는가? ShiftHandover-Item-Ack 3계층")
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useCan } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { fieldLabel } from '@/features/handovers/VersionHistory'
import { shiftApi, type ShiftSession } from '@/services/api/shift'

type Direction = 'received' | 'sent' | 'all' | 'team'

function when(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export default function HistoryView() {
  const can = useCan()
  const [params, setParams] = useSearchParams()
  const [direction, setDirection] = useState<Direction>('received')
  const selected = params.get('session') ? Number(params.get('session')) : null

  const { data } = useQuery({
    queryKey: ['shift-history', direction], queryFn: () => shiftApi.history(direction),
  })

  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id == null) next.delete('session'); else next.set('session', String(id))
    setParams(next, { replace: true })
  }

  const tabs: { key: Direction; label: string }[] = [
    { key: 'received', label: '받은 인계' }, { key: 'sent', label: '보낸 인계' },
    { key: 'all', label: '내 전체' },
    ...(can('handover:update_any') ? [{ key: 'team' as Direction, label: '팀 전체' }] : []),
  ]

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 min-w-0 p-3 space-y-2 overflow-auto">
        <div className="flex gap-1" role="tablist">
          {tabs.map((t) => (
            <button key={t.key} role="tab" aria-selected={direction === t.key}
                    className={`btn btn-sm ${direction === t.key ? 'btn-primary' : ''}`}
                    onClick={() => setDirection(t.key)}>{t.label}</button>
          ))}
        </div>
        <table className="w-full text-base border border-surface-border rounded">
          <thead className="bg-surface-sunken text-ink-muted">
            <tr>
              <th className="text-left font-medium px-2 py-1">전달 시각</th>
              <th className="text-left font-medium px-2 py-1">보낸 사람 → 받은 사람</th>
              <th className="text-right font-medium px-2 py-1">항목</th>
              <th className="text-left font-medium px-2 py-1">확인</th>
              <th className="text-left font-medium px-2 py-1">상태</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-ink-faint">인계 기록이 없습니다.</td></tr>
            )}
            {(data ?? []).map((s) => (
              <tr key={s.id} onClick={() => select(s.id)}
                  className={`border-t border-surface-border/60 cursor-pointer ${selected === s.id ? 'bg-brand-soft' : 'hover:bg-surface-sunken'}`}>
                <td className="px-2 py-1 tabular-nums">{when(s.sent_at)}</td>
                <td className="px-2 py-1">{s.from_user} → {s.to_user}</td>
                <td className="px-2 py-1 text-right tabular-nums">{s.item_count}</td>
                <td className="px-2 py-1 tabular-nums">
                  <span className={s.acked_count === s.item_count ? 'text-state-done' : 'text-state-check'}>
                    {s.acked_count}/{s.item_count}
                  </span>
                </td>
                <td className="px-2 py-1">{s.status === 'CLOSED' ? '종료' : '진행 중'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected != null && <SessionDetail id={selected} onClose={() => select(null)} />}
    </div>
  )
}

function SessionDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const { data: s } = useQuery({ queryKey: ['shift-session', id], queryFn: () => shiftApi.session(id) })
  const close = useMutation({
    mutationFn: () => shiftApi.close(id),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['shift-session', id] })
      qc.invalidateQueries({ queryKey: ['shift-history'] })
    },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '종료하지 못했습니다.'),
  })

  if (!s) return <aside className="w-[520px] border-l border-surface-border grid place-items-center text-ink-faint">불러오는 중…</aside>

  return (
    <aside className="w-[520px] shrink-0 border-l border-surface-border bg-surface flex flex-col min-h-0"
           aria-label="인계 상세">
      <div className="px-3 py-2 border-b border-surface-border">
        <div className="flex items-center gap-2">
          <h2 className="font-medium flex-1">인계 #{s.id}</h2>
          <button className="text-ink-faint hover:text-ink" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <p className="text-ink-muted">
          {s.from_user} → {s.to_user} · {when(s.sent_at)} · 확인 {s.acked_count}/{s.item_count}
        </p>
      </div>
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {s.summary_note && <p className="bg-surface-sunken rounded px-2 py-1 whitespace-pre-wrap">{s.summary_note}</p>}
        <ul className="space-y-1">
          {[...s.items].sort((a, b) => a.display_order - b.display_order).map((i) => (
            <li key={i.item_id} className="border border-surface-border rounded px-2 py-1.5">
              <button className="text-left hover:underline" onClick={() => navigate(`/handovers?id=${i.handover_id}`)}>
                <span className="tabular-nums text-ink-faint mr-1">#{i.handover_id}</span>{i.title}
              </button>
              <div className="text-sm text-ink-muted flex flex-wrap gap-x-2">
                <span>{i.company} · {i.status}</span>
                <span className="tabular-nums">전달 v{i.version_no_at_transfer} · 현재 v{i.current_version_no}</span>
                {i.changed_since_transfer && <span className="text-state-check">⚠ 전달 이후 변경</span>}
                {i.carry_depth > 1 && <span className="text-state-check">{i.carry_depth}교대째</span>}
              </div>
              <div className="text-sm">
                {i.ack_state === 'ACKED' && <span className="text-state-done">✔ v{i.acked_version_no} 확인</span>}
                {i.ack_state === 'PENDING' && <span className="text-state-wait">○ 아직 확인 안 함</span>}
                {i.ack_state === 'REACK_REQUIRED' && (
                  <span className="text-state-check">⚠ 확인 후 변경됨 — 다시 확인 필요
                    {i.stale_reason?.length ? ` (${i.stale_reason.map(fieldLabel).join(', ')})` : ''}</span>
                )}
              </div>
              {i.item_note && <div className="text-sm">📝 {i.item_note}</div>}
            </li>
          ))}
        </ul>
        {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}
      </div>
      {s.status === 'SENT' && (
        <div className="p-3 border-t border-surface-border">
          <button className="btn w-full justify-center" disabled={close.isPending || !allAcked(s)}
                  onClick={() => close.mutate()}
                  title={allAcked(s) ? '' : '받는 사람이 모두 확인해야 닫을 수 있습니다'}>
            <Lock size={12} /> 인계 종료 {allAcked(s) ? '' : `(미확인 ${s.item_count - s.acked_count}건)`}
          </button>
        </div>
      )}
    </aside>
  )
}

function allAcked(s: ShiftSession): boolean {
  return s.items.filter((i) => !i.is_deleted).every((i) => i.ack_state === 'ACKED')
}
