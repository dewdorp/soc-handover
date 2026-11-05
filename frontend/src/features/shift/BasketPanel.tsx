/**
 * 다음 교대 인계 Basket (UI_STRUCTURE §5).
 *
 * 처음 열면 직전 교대에서 넘어온 미완료가 자동으로 담긴다. 빼는 것은 사람이 한다 —
 * 무엇을 넘겼는지는 사람의 명시적 선택이어야 증적으로서 의미가 있다(B-06).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Send, X } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import { rosterApi } from '@/services/api/roster'
import { shiftApi, type SessionItem } from '@/services/api/shift'

interface Props {
  nextShiftLabel: string
}

/**
 * 입력을 멈추고 잠시 뒤 저장한다. 포커스를 잃을 때만 저장하면 새로고침·창 닫기에
 * 적던 총평·메모가 날아간다. 사용자가 입력했을 때만 동작하므로 불러온 값을 되쓰지 않는다.
 */
function useAutosave(save: (value: string) => void, delay = 800) {
  const latest = useRef(save)
  latest.current = save
  const timer = useRef<number>()
  const pending = useRef<string | null>(null)
  const flush = () => {
    window.clearTimeout(timer.current)
    if (pending.current !== null) latest.current(pending.current)
    pending.current = null
  }
  useEffect(() => flush, [])  // eslint-disable-line react-hooks/exhaustive-deps -- 화면을 떠날 때 남은 입력 저장
  const schedule = (value: string) => {
    pending.current = value
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(flush, delay)
  }
  return { schedule, flush }
}

export default function BasketPanel({ nextShiftLabel }: Props) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [summary, setSummary] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sentMessage, setSentMessage] = useState<string | null>(null)
  const [carryNotice, setCarryNotice] = useState<number>(0)
  const [confirming, setConfirming] = useState(false)

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

  // 인수자를 손으로 고르게 두면 근무표가 바뀐 날(대근·맞교환) 엉뚱한 사람에게 넘어간다.
  // 그래서 다음 근무의 **실제** 근무자를 서버에 물어 한 번에 채울 수 있게 한다.
  const nextShift = useQuery({ queryKey: ['next-shift'], queryFn: rosterApi.nextShift,
                               staleTime: 60_000 })

  const patch = useMutation({ mutationFn: shiftApi.updateBasket, onSuccess: refresh })
  const remove = useMutation({ mutationFn: shiftApi.removeItem, onSuccess: refresh })
  const note = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => shiftApi.noteItem(id, text || null),
    onSuccess: refresh,
  })
  const summarySave = useAutosave((value) => {
    if (value !== (basket?.summary_note ?? '')) patch.mutate({ summary_note: value || null })
  })
  const candidates = (users ?? []).filter((u) => u.id !== me?.id)
  // 서버에 저장되기 전에도 고른 대로 보여 준다 — 두 명을 빠르게 고르면 먼저 고른 사람이
  // 아직 안 담긴 목록을 읽어 사라진다(저장은 목록 전체를 보내므로).
  const [localIds, setLocalIds] = useState<number[] | null>(null)
  const chosenIds = localIds ?? basket?.to_user_ids ?? []
  useEffect(() => {
    if (localIds && basket && localIds.join() === basket.to_user_ids.join()) setLocalIds(null)
  }, [basket, localIds])
  const chosen = chosenIds.map((id) => ({
    id, name: candidates.find((u) => u.id === id)?.display_name ?? `#${id}`,
  }))
  const setRecipients = (ids: number[]) => { setLocalIds(ids); patch.mutate({ to_user_ids: ids }) }

  const send = useMutation({
    mutationFn: () => shiftApi.send({ to_user_ids: chosenIds, summary_note: summary || null }),
    onSuccess: (session) => {
      setError(null)
      setCarryNotice(0)
      setSentMessage(`${session.to_users.join(' · ')} 님에게 ${session.item_count}건을 인계했습니다.`)
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

  return (
    <aside className="w-full lg:w-[380px] shrink-0 max-lg:border-t lg:border-l border-surface-border bg-surface flex flex-col lg:min-h-0"
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

        <div className="space-y-0.5">
          <span className="text-ink-muted" id="recipients-label">받는 사람 ({nextShiftLabel})</span>
          {chosen.length > 0 && (
            <ul className="flex flex-wrap gap-1" aria-labelledby="recipients-label">
              {chosen.map((r) => (
                <li key={r.id} className="chip flex items-center gap-1">
                  {r.name}
                  <button aria-label={`${r.name} 빼기`} className="text-ink-faint hover:text-state-urgent"
                          onClick={() => setRecipients(chosenIds.filter((id) => id !== r.id))}>
                    <X size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {nextShift.data && nextShift.data.user_ids.length > 0 && (
            <div className="rounded border border-surface-border bg-surface-sunken px-2 py-1 space-y-0.5">
              <p className="text-sm">
                <span className="text-ink-muted">다음 근무 실근무자</span>{' '}
                <span className="font-medium">{nextShift.data.names.join(' · ')}</span>
                {nextShift.data.team_code && (
                  <span className="text-ink-faint"> ({nextShift.data.team_code}조)</span>)}
              </p>
              {nextShift.data.replaced.length > 0 && (
                <p className="text-xs text-state-check">
                  {nextShift.data.replaced.map((c) => (
                    `${c.off_user_name} → ${c.on_user_name}`)).join(', ')} (대근 · 맞교환 반영)
                </p>
              )}
              {nextShift.data.is_short && (
                <p className="text-xs text-state-urgent">결원 {nextShift.data.short_by}명 — 받을 사람이 부족합니다.</p>
              )}
              <button className="btn btn-sm"
                      disabled={nextShift.data.user_ids.filter((id) => id !== me?.id)
                        .every((id) => chosenIds.includes(id))}
                      onClick={() => setRecipients([...new Set([
                        ...chosenIds,
                        ...nextShift.data!.user_ids.filter((id) => id !== me?.id),
                      ])])}>
                실근무자로 채우기
              </button>
            </div>
          )}
          <select className="input w-full" value="" aria-label="받는 사람 추가"
                  onChange={(e) => {
                    if (e.target.value) setRecipients([...chosenIds, Number(e.target.value)])
                  }}>
            <option value="">{chosen.length ? '+ 인수자 추가' : '(선택)'}</option>
            {candidates.filter((u) => !chosenIds.includes(u.id))
              .map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
          {chosen.length > 1 && (
            <p className="text-xs text-ink-faint">{chosen.length}명 모두가 확인해야 인계가 끝납니다.</p>
          )}
        </div>

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
                    onChange={(e) => { setSummary(e.target.value); summarySave.schedule(e.target.value) }}
                    onBlur={summarySave.flush} />
        </label>

        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">
            {error}
          </p>
        )}
      </div>

      <div className="p-3 border-t border-surface-border">
        <button className="btn btn-primary w-full justify-center h-8"
                disabled={!items.length || !chosen.length || send.isPending}
                onClick={() => setConfirming(true)}>
          <Send size={13} /> 다음 근무자에게 인계
        </button>
        {confirming && (
          <ConfirmDialog
            title={`${chosen.map((r) => r.name).join(' · ') || '받는 사람'} 님에게 ${items.length}건을 인계합니다`}
            confirmLabel="인계" busy={send.isPending}
            onCancel={() => setConfirming(false)}
            onConfirm={() => { setConfirming(false); send.mutate() }}>
            <p>항목마다 지금 버전이 기록되고, 받는 사람{chosen.length > 1 ? ' 모두가' : '이'} 확인해야 끝납니다.</p>
            {!summary.trim() && <p className="text-state-check">교대 총평이 비어 있습니다.</p>}
          </ConfirmDialog>
        )}
        {!chosen.length && items.length > 0 && (
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
  const noteSave = useAutosave((value) => { if (value !== (item.item_note ?? '')) onNote(value) })

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
             onChange={(e) => { setText(e.target.value); noteSave.schedule(e.target.value) }}
             onBlur={noteSave.flush} />
    </li>
  )
}
