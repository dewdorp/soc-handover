/**
 * 인수 확인함 (UI_STRUCTURE §5.1) — 나에게 넘어온 것 중 확인하지 않았거나 다시 확인해야 할 것.
 *
 * 확인은 '누른 순간의 버전'으로 기록된다. 전달 뒤에 내용이 바뀌었으면 그 사실을 먼저
 * 보여줘서, 바뀐 내용을 모른 채 확인 버튼만 누르는 일을 줄인다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Check, CheckCheck } from 'lucide-react'
import { fieldLabel } from '@/features/handovers/VersionHistory'
import { shiftApi, type InboxItem } from '@/services/api/shift'

function when(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export default function InboxView() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const { data } = useQuery({ queryKey: ['inbox'], queryFn: shiftApi.inbox, refetchInterval: 30_000 })
  const rows = data ?? []

  const ack = useMutation({
    mutationFn: (ids: number[]) => shiftApi.bulkAck(ids),
    onSuccess: () => {
      setPicked(new Set())
      for (const key of ['inbox', 'me', 'cockpit', 'handovers', 'shift-history']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
    },
  })

  const toggle = (id: number) => {
    const next = new Set(picked)
    next.has(id) ? next.delete(id) : next.add(id)
    setPicked(next)
  }

  return (
    <div className="p-3 space-y-2 overflow-auto">
      <div className="flex items-center gap-2">
        <p className={rows.length ? 'text-state-check font-medium' : 'text-ink-muted'}>
          {rows.length ? `⚠ 확인하지 않은 인수인계 ${rows.length}건이 있습니다.` : '확인할 인수인계가 없습니다.'}
        </p>
        <span className="flex-1" />
        <button className="btn btn-primary btn-sm" disabled={!picked.size || ack.isPending}
                onClick={() => ack.mutate([...picked])}>
          <CheckCheck size={12} /> 선택 {picked.size}건 확인
        </button>
      </div>

      {rows.length > 0 && (
        <table className="w-full text-base border border-surface-border rounded">
          <thead className="bg-surface-sunken text-ink-muted">
            <tr>
              <th className="w-8 px-2 py-1">
                <input type="checkbox" aria-label="전체 선택" checked={rows.every((r) => picked.has(r.handover_id))}
                       onChange={(e) => setPicked(e.target.checked ? new Set(rows.map((r) => r.handover_id)) : new Set())} />
              </th>
              <th className="text-left font-medium px-2 py-1">인수인계</th>
              <th className="text-left font-medium px-2 py-1">버전</th>
              <th className="text-left font-medium px-2 py-1">넘겨준 사람</th>
              <th className="text-left font-medium px-2 py-1">상태</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => <Row key={r.handover_id} r={r} picked={picked.has(r.handover_id)}
                                  onToggle={() => toggle(r.handover_id)}
                                  onOpen={() => navigate(`/handovers?id=${r.handover_id}`)}
                                  onAck={() => ack.mutate([r.handover_id])} busy={ack.isPending} />)}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Row({ r, picked, onToggle, onOpen, onAck, busy }: {
  r: InboxItem; picked: boolean; onToggle: () => void; onOpen: () => void; onAck: () => void; busy: boolean
}) {
  const changedAfterTransfer = r.version_no_at_transfer != null && r.current_version_no > r.version_no_at_transfer
  return (
    <tr className="border-t border-surface-border/60 align-top">
      <td className="px-2 py-1.5 text-center">
        <input type="checkbox" checked={picked} onChange={onToggle} aria-label={`#${r.handover_id} 선택`} />
      </td>
      <td className="px-2 py-1.5 max-w-[420px]">
        <button className="text-left hover:underline" onClick={onOpen}>
          <span className="tabular-nums text-ink-faint mr-1">#{r.handover_id}</span>
          {r.priority_code === 'URGENT' && <span className="text-state-urgent mr-1">⛔</span>}
          {r.title}
        </button>
        <div className="text-xs text-ink-muted">
          {r.company} · {r.status}
          {r.carry_depth && r.carry_depth > 1 && <span className="text-state-check"> · {r.carry_depth}교대째 인계 중</span>}
        </div>
        {r.item_note && <div className="text-sm text-ink mt-0.5">📝 {r.item_note}</div>}
      </td>
      <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">
        v{r.current_version_no}
        {changedAfterTransfer && (
          <div className="text-xs text-state-check">전달 v{r.version_no_at_transfer} 이후 변경</div>
        )}
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        {r.from_user ?? '-'} → 나
        <div className="text-xs text-ink-faint">{when(r.sent_at)}</div>
      </td>
      <td className="px-2 py-1.5">
        {r.state === 'REACK_REQUIRED' ? (
          <span className="text-state-check font-medium">
            ⚠ 확인 후 변경됨 (v{r.acked_version_no} 확인)
            {r.stale_reason?.length ? <span className="block text-xs font-normal">
              바뀐 것: {r.stale_reason.map(fieldLabel).join(', ')}</span> : null}
          </span>
        ) : <span className="text-state-wait">○ 대기</span>}
      </td>
      <td className="px-2 py-1.5 text-right">
        <button className="btn btn-sm" disabled={busy} onClick={onAck}>
          <Check size={11} /> {r.state === 'REACK_REQUIRED' ? '재확인' : '확인'}
        </button>
      </td>
    </tr>
  )
}
