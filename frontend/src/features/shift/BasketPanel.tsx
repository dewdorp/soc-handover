/**
 * 다음 교대 인계 Basket (UI_STRUCTURE §5).
 *
 * 처음 열면 직전 교대에서 넘어온 미완료가 자동으로 담긴다. 빼는 것은 사람이 한다 —
 * 무엇을 넘겼는지는 사람의 명시적 선택이어야 증적으로서 의미가 있다(B-06).
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Send, X } from 'lucide-react'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import { shiftApi, type SessionItem } from '@/services/api/shift'

interface Props {
  nextShiftLabel: string
}

export default function BasketPanel({ nextShiftLabel }: Props) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [summary, setSummary] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sentMessage, setSentMessage] = useState<string | null>(null)
  const [carryNotice, setCarryNotice] = useState<number>(0)

  const { data: basket } = useQuery({ queryKey: ['basket'], queryFn: shiftApi.basket })
  const { data: users } = useQuery({
    queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000,
  })

  useEffect(() => {
    if (basket?.auto_added) setCarryNotice(basket.auto_added)
    setSummary(basket?.summary_note ?? '')
  }, [basket?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['basket'] })
    qc.invalidateQueries({ queryKey: ['cockpit'] })
  }

  const patch = useMutation({ mutationFn: shiftApi.updateBasket, onSuccess: refresh })
  const remove = useMutation({ mutationFn: shiftApi.removeItem, onSuccess: refresh })
  const note = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => shiftApi.noteItem(id, text || null),
    onSuccess: refresh,
  })
  const send = useMutation({
    mutationFn: () => shiftApi.send({ to_user_id: basket!.to_user_id!, summary_note: summary || null }),
    onSuccess: (session) => {
      setError(null)
      setCarryNotice(0)
      setSentMessage(`${session.to_user} 님에게 ${session.item_count}건을 인계했습니다.`)
      refresh()
      qc.invalidateQueries({ queryKey: ['shift-history'] })
    },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '인계하지 못했습니다.'),
  })

  const items = useMemo(() => [...(basket?.items ?? [])]
    .sort((a, b) => a.display_order - b.display_order), [basket])

  const move = (index: number, delta: number) => {
    const order = items.map((i) => i.item_id)
    const target = index + delta
    if (target < 0 || target >= order.length) return
    ;[order[index], order[target]] = [order[target], order[index]]
    patch.mutate({ order })
  }

  const recipients = (users ?? []).filter((u) => u.id !== me?.id)

  return (
    <aside className="w-[380px] shrink-0 border-l border-surface-border bg-surface flex flex-col min-h-0"
           aria-label="다음 교대 인계 Basket">
      <div className="px-3 py-2 border-b border-surface-border flex items-center gap-2">
        <h2 className="font-medium flex-1">다음 교대 인계 Basket</h2>
        <span className="chip tabular-nums">{items.length}</span>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-2">
        {sentMessage && (
          <p role="status" className="text-sm text-state-done bg-green-50 border border-green-200 rounded px-2 py-1">
            ✔ {sentMessage}
          </p>
        )}
        {carryNotice > 0 && (
          <p className="text-sm bg-amber-50 border border-amber-200 text-amber-800 rounded px-2 py-1">
            직전 교대에서 넘어온 미완료 {carryNotice}건이 자동으로 담겼습니다. 이번에 넘기지 않을 것은 빼십시오.
          </p>
        )}

        <label className="block space-y-0.5">
          <span className="text-ink-muted">받는 사람 ({nextShiftLabel})</span>
          <select className="input w-full" value={basket?.to_user_id ?? ''}
                  onChange={(e) => patch.mutate({ to_user_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">(선택)</option>
            {recipients.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        </label>

        {items.length === 0 && (
          <p className="text-ink-faint text-sm py-4 text-center">
            왼쪽 목록에서 넘길 항목을 골라 담으십시오.
          </p>
        )}

        <ul className="space-y-1">
          {items.map((item, i) => (
            <BasketItem key={item.item_id} item={item}
                        onUp={() => move(i, -1)} onDown={() => move(i, 1)}
                        onRemove={() => remove.mutate(item.item_id)}
                        onNote={(text) => note.mutate({ id: item.item_id, text })} />
          ))}
        </ul>

        <label className="block space-y-0.5">
          <span className="text-ink-muted">교대 총평</span>
          <textarea className="input w-full h-20 py-1 resize-y" value={summary}
                    placeholder="이번 근무 전체 상황을 한두 줄로"
                    onChange={(e) => setSummary(e.target.value)}
                    onBlur={() => summary !== (basket?.summary_note ?? '') && patch.mutate({ summary_note: summary || null })} />
        </label>

        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">
            {error}
          </p>
        )}
      </div>

      <div className="p-3 border-t border-surface-border">
        <button className="btn btn-primary w-full justify-center h-8"
                disabled={!items.length || !basket?.to_user_id || send.isPending}
                onClick={() => {
                  const who = recipients.find((u) => u.id === basket?.to_user_id)?.display_name
                  if (window.confirm(`${who} 님에게 ${items.length}건을 인계합니다. `
                    + '항목마다 지금 버전이 기록되고, 받는 사람이 확인해야 끝납니다.')) send.mutate()
                }}>
          <Send size={13} /> 다음 근무자에게 인계
        </button>
        {!basket?.to_user_id && items.length > 0 && (
          <p className="text-xs text-ink-faint mt-1 text-center">받는 사람을 먼저 고르십시오.</p>
        )}
      </div>
    </aside>
  )
}

function BasketItem({ item, onUp, onDown, onRemove, onNote }: {
  item: SessionItem; onUp: () => void; onDown: () => void; onRemove: () => void
  onNote: (text: string) => void
}) {
  const [text, setText] = useState(item.item_note ?? '')
  useEffect(() => setText(item.item_note ?? ''), [item.item_note])

  return (
    <li className="border border-surface-border rounded px-2 py-1.5 space-y-1">
      <div className="flex items-start gap-1">
        <div className="flex flex-col">
          <button onClick={onUp} aria-label="위로" className="text-ink-faint hover:text-ink"><ArrowUp size={11} /></button>
          <button onClick={onDown} aria-label="아래로" className="text-ink-faint hover:text-ink"><ArrowDown size={11} /></button>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <span className="tabular-nums text-ink-faint">#{item.handover_id}</span>
            {item.priority_code === 'URGENT' && <span className="text-state-urgent" title="긴급">⛔</span>}
            {item.priority_code === 'HIGH' && <span className="text-state-high" title="높음">▲</span>}
            <span className="truncate" title={item.title}>{item.title}</span>
          </div>
          <div className="text-xs text-ink-muted flex gap-1.5">
            <span>{item.company}</span>
            <span>· {item.status}</span>
            {item.carry_depth > 1 && (
              <span className="text-state-check font-medium">· {item.carry_depth}교대째 인계 중</span>
            )}
          </div>
        </div>
        <button onClick={onRemove} aria-label="빼기" className="text-ink-faint hover:text-state-urgent"><X size={13} /></button>
      </div>
      <input className="input w-full h-6 text-sm" placeholder="메모 (예: 02시 재점검 필요)" value={text}
             onChange={(e) => setText(e.target.value)}
             onBlur={() => text !== (item.item_note ?? '') && onNote(text)} />
    </li>
  )
}
