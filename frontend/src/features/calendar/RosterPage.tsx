/**
 * 근무표 (/schedules/roster) — 4조 2교대.
 *
 * 화면이 지키는 두 가지
 *   · **계획과 실제를 같이** 보여 준다. 대근으로 빠진 사람은 취소선, 들어온 사람은 굵게.
 *     계획만 보면 대근 당일에 엉뚱한 사람에게 인계한다.
 *   · 결원은 숨기지 않는다. 정원보다 적게 서는 근무는 줄 전체에 표시가 남는다.
 *
 * 좁은 화면에서는 표가 아니라 카드로 쌓인다(현장 PC 는 1280 이지만 노트북으로 보는 일도 있다).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, ChevronLeft, ChevronRight, UserMinus, X } from 'lucide-react'
import { useCan } from '@/hooks/useAuth'
import { useEscape } from '@/hooks/useHotkeys'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import { rosterApi, type ShiftStaffing } from '@/services/api/roster'

type View = 'week' | 'month'

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function startOfWeek(d: Date): Date {
  const copy = new Date(d)
  const weekday = (copy.getDay() + 6) % 7      // 월요일 = 0
  copy.setDate(copy.getDate() - weekday)
  return copy
}

const WEEKDAY = ['월', '화', '수', '목', '금', '토', '일']

export default function RosterPage() {
  const can = useCan()
  const qc = useQueryClient()
  const [view, setView] = useState<View>('week')
  const [anchor, setAnchor] = useState(() => startOfWeek(new Date()))
  const [mine, setMine] = useState(false)
  const [editing, setEditing] = useState<ShiftStaffing | null>(null)
  const [swapping, setSwapping] = useState<ShiftStaffing | null>(null)
  const [error, setError] = useState<string | null>(null)

  const start = useMemo(
    () => (view === 'week' ? isoDay(anchor) : isoDay(new Date(anchor.getFullYear(), anchor.getMonth(), 1))),
    [view, anchor])

  const { data, isFetching } = useQuery({
    queryKey: ['roster', view, start, mine],
    queryFn: () => rosterApi.calendar(view, start, mine),
  })
  const upcoming = useQuery({ queryKey: ['roster-mine'], queryFn: () => rosterApi.mine(14) })
  const coverage = useQuery({ queryKey: ['roster-coverage', start], queryFn: () => rosterApi.coverage(start, 32) })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['roster-mine'] })
    qc.invalidateQueries({ queryKey: ['roster-coverage'] })
  }
  const fail = (err: unknown) => setError(err instanceof ApiRequestError ? err.message : '처리하지 못했습니다.')

  const cancel = useMutation({
    mutationFn: (id: number) => rosterApi.cancel(id, '되돌림'),
    onSuccess: () => { setError(null); refresh() }, onError: fail,
  })

  const step = (dir: 1 | -1) => {
    const next = new Date(anchor)
    if (view === 'week') next.setDate(next.getDate() + dir * 7)
    else next.setMonth(next.getMonth() + dir)
    setAnchor(view === 'week' ? startOfWeek(next) : next)
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex flex-wrap items-center gap-2 px-3 pt-2">
        <h1 className="text-md font-medium">근무표</h1>
        <div className="flex items-center gap-0.5">
          <button className="btn btn-sm" onClick={() => step(-1)} aria-label="이전"><ChevronLeft size={14} /></button>
          <button className="btn btn-sm" onClick={() => setAnchor(startOfWeek(new Date()))}>오늘</button>
          <button className="btn btn-sm" onClick={() => step(1)} aria-label="다음"><ChevronRight size={14} /></button>
        </div>
        <div className="flex rounded border border-surface-border overflow-hidden">
          {(['week', 'month'] as View[]).map((v) => (
            <button key={v} onClick={() => setView(v)}
                    className={`px-2 h-7 text-sm ${view === v ? 'bg-brand text-white' : 'bg-surface'}`}>
              {v === 'week' ? '주' : '월'}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-sm cursor-pointer">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          내 근무만
        </label>
        <span className="text-sm text-ink-faint">
          {data ? `${data.start} ~ ${data.end} · ${data.cycle_days}일 주기` : ''}
        </span>
      </div>

      {error && (
        <p role="alert" className="mx-3 mt-2 text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">
          {error}
        </p>
      )}
      {coverage.data && !coverage.data.ok && (
        <p role="alert" className="mx-3 mt-2 text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">
          <AlertTriangle size={12} className="inline mr-1" />
          주기가 맞물리지 않습니다 — {coverage.data.problems[0].day} 에 주간 {coverage.data.problems[0].day_teams.length}조 ·
          야간 {coverage.data.problems[0].night_teams.length}조. 관리자 화면에서 조의 주기 위치를 확인하십시오.
        </p>
      )}

      <div className={`flex-1 min-h-0 overflow-auto p-3 space-y-3 ${isFetching ? 'opacity-70' : ''}`}>
        <section className="space-y-1.5">
          {(data?.days ?? []).map((d) => {
            const date = new Date(`${d.day}T00:00:00`)
            const todayish = d.day === isoDay(new Date())
            return (
              <div key={d.day}
                   className={`border rounded ${todayish ? 'border-brand' : 'border-surface-border'} bg-surface`}>
                <div className="flex items-center gap-2 px-2 py-1 bg-surface-sunken text-sm">
                  <span className="font-medium tabular-nums">{d.day.slice(5)}</span>
                  <span className="text-ink-muted">{WEEKDAY[(date.getDay() + 6) % 7]}</span>
                  {todayish && <span className="text-brand text-xs">오늘</span>}
                  <span className="flex-1" />
                  {d.off_team_codes.length > 0 && (
                    <span className="text-ink-faint text-xs">비번 {d.off_team_codes.join(' · ')}</span>)}
                </div>
                <div className="divide-y divide-surface-border">
                  {d.shifts.map((s) => (
                    <ShiftRow key={s.shift_code} row={s}
                              canManage={can('shift:manage')}
                              onSubstitute={() => setEditing(s)}
                              onSwap={() => setSwapping(s)}
                              onCancel={(id) => cancel.mutate(id)} />
                  ))}
                  {d.shifts.length === 0 && (
                    <p className="px-2 py-1.5 text-sm text-ink-faint">내 근무가 없는 날</p>)}
                </div>
              </div>
            )
          })}
        </section>

        <section className="border border-surface-border rounded bg-surface p-2">
          <h2 className="font-medium mb-1">내 근무 (14일)</h2>
          {upcoming.data?.length
            ? (
              <ul className="text-base divide-y divide-surface-border">
                {upcoming.data.map((s) => (
                  <li key={`${s.work_date}${s.shift_code}`} className="py-1 flex flex-wrap items-center gap-2">
                    <span className="tabular-nums font-medium">{s.work_date.slice(5)}</span>
                    <span className={s.shift_code === 'NIGHT' ? 'text-state-waiting' : 'text-brand'}>
                      {s.shift_label}
                    </span>
                    <span className="text-sm text-ink-muted">
                      {s.start_at.slice(11, 16)} ~ {s.end_at.slice(5, 10)} {s.end_at.slice(11, 16)}
                    </span>
                    {s.with_names.length > 0 && (
                      <span className="text-sm text-ink-faint">함께: {s.with_names.join(' · ')}</span>)}
                    {s.is_short && <span className="text-sm text-state-urgent">결원 {s.short_by}명</span>}
                  </li>
                ))}
              </ul>
            )
            : <p className="text-sm text-ink-faint">앞으로 14일 안에 배정된 근무가 없습니다.</p>}
        </section>
      </div>

      {editing && (
        <SubstituteDialog row={editing} onClose={() => setEditing(null)}
                          onDone={() => { setEditing(null); refresh() }} onError={fail} />
      )}
      {swapping && (
        <SwapDialog row={swapping} onClose={() => setSwapping(null)}
                    onDone={() => { setSwapping(null); refresh() }} onError={fail} />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- 한 근무 줄

function ShiftRow({ row, canManage, onSubstitute, onSwap, onCancel }: {
  row: ShiftStaffing
  canManage: boolean
  onSubstitute: () => void
  onSwap: () => void
  onCancel: (id: number) => void
}) {
  const removed = new Set(row.changes.map((c) => c.off_user_id))
  const added = new Set(row.changes.map((c) => c.on_user_id).filter((x): x is number => x != null))

  return (
    <div className={`px-2 py-1.5 flex flex-wrap items-center gap-2 ${row.is_mine ? 'bg-brand/5' : ''}`}>
      <span className={`w-10 shrink-0 text-sm ${row.shift_code === 'NIGHT' ? 'text-state-waiting' : 'text-brand'}`}>
        {row.shift_label}
      </span>
      <span className="w-8 shrink-0 text-sm text-ink-muted">{row.team_code ?? '—'}</span>

      <span className="flex-1 min-w-[12rem] flex flex-wrap gap-x-2 gap-y-0.5">
        {row.planned_user_ids.map((uid, i) => (
          <span key={uid} className={removed.has(uid) ? 'line-through text-ink-faint' : ''}>
            {row.planned_names[i]}
          </span>
        ))}
        {row.actual_user_ids.filter((uid) => added.has(uid)).map((uid) => (
          <span key={`in-${uid}`} className="font-medium text-state-done">
            + {row.actual_names[row.actual_user_ids.indexOf(uid)]}
          </span>
        ))}
        {row.planned_user_ids.length === 0 && <span className="text-ink-faint text-sm">배정 없음</span>}
      </span>

      {row.is_short && (
        <span className="text-sm text-state-urgent inline-flex items-center gap-1">
          <AlertTriangle size={11} /> {row.actual_user_ids.length}/{row.expected} 결원 {row.short_by}명
        </span>
      )}
      {row.is_mine && <span className="text-xs text-brand">내 근무</span>}

      {canManage && (
        <span className="flex items-center gap-1">
          <button className="btn btn-sm" onClick={onSubstitute} disabled={!row.actual_user_ids.length}>
            <UserMinus size={11} /> 대근 · 결원
          </button>
          <button className="btn btn-sm" onClick={onSwap} disabled={!row.actual_user_ids.length}>
            <ArrowLeftRight size={11} /> 맞교환
          </button>
        </span>
      )}

      {row.changes.length > 0 && (
        <ul className="w-full text-sm text-ink-muted pl-12 space-y-0.5">
          {row.changes.map((c) => (
            <li key={c.id} className="flex items-center gap-1.5">
              <span>
                {c.kind === 'OFF' ? '결원' : c.kind === 'SWAP' ? '맞교환' : '대근'}:
                {' '}{c.off_user_name}
                {c.on_user_name ? ` → ${c.on_user_name}` : ' (대체 없음)'}
                {c.reason ? ` · ${c.reason}` : ''}
              </span>
              {canManage && (
                <button className="btn btn-sm" onClick={() => onCancel(c.id)}>되돌리기</button>)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- 대근 · 결원

function SubstituteDialog({ row, onClose, onDone, onError }: {
  row: ShiftStaffing
  onClose: () => void
  onDone: () => void
  onError: (e: unknown) => void
}) {
  useEscape(onClose)
  const [off, setOff] = useState(String(row.actual_user_ids[0] ?? ''))
  const [on, setOn] = useState('')
  const [reason, setReason] = useState('')
  const users = useQuery({ queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000 })

  const save = useMutation({
    mutationFn: () => rosterApi.substitute({
      work_date: row.work_date, shift_code: row.shift_code,
      off_user_id: Number(off), on_user_id: on ? Number(on) : null,
      reason: reason.trim() || null,
    }),
    onSuccess: onDone, onError,
  })

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-start justify-center p-4"
         role="dialog" aria-modal="true" aria-label="대근 · 결원 등록">
      <form className="bg-surface rounded shadow-lg border border-surface-border w-full max-w-md mt-16 p-3 space-y-2"
            onSubmit={(e) => { e.preventDefault(); if (off) save.mutate() }}>
        <div className="flex items-center">
          <h3 className="font-medium flex-1">{row.work_date} {row.shift_label} · 대근 · 결원</h3>
          <button type="button" className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={14} /></button>
        </div>
        <label className="block text-sm">
          빠지는 사람 *
          <select className="input w-full mt-0.5" value={off} onChange={(e) => setOff(e.target.value)} required>
            {row.actual_user_ids.map((uid, i) => (
              <option key={uid} value={uid}>{row.actual_names[i]}</option>))}
          </select>
        </label>
        <label className="block text-sm">
          들어오는 사람 (비우면 결원)
          <select className="input w-full mt-0.5" value={on} onChange={(e) => setOn(e.target.value)}>
            <option value="">— 대체 없음(결원으로 표시) —</option>
            {(users.data ?? [])
              .filter((u) => !row.actual_user_ids.includes(u.id))
              .map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          사유
          <input className="input w-full mt-0.5" value={reason} maxLength={500}
                 onChange={(e) => setReason(e.target.value)} placeholder="병가 · 교육 · 비상 대기" />
        </label>
        <p className="text-sm text-ink-faint">
          계획표는 그대로 남고 '실제 근무자'만 바뀝니다. 당사자에게 알림이 갑니다.
        </p>
        <div className="flex justify-end gap-1 pt-1">
          <button type="button" className="btn btn-sm" onClick={onClose}>취소</button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={!off || save.isPending}>등록</button>
        </div>
      </form>
    </div>
  )
}

// --------------------------------------------------------------------------- 맞교환

function SwapDialog({ row, onClose, onDone, onError }: {
  row: ShiftStaffing
  onClose: () => void
  onDone: () => void
  onError: (e: unknown) => void
}) {
  useEscape(onClose)
  const [mineUser, setMineUser] = useState(String(row.actual_user_ids[0] ?? ''))
  const [otherDate, setOtherDate] = useState(row.work_date)
  const [otherShift, setOtherShift] = useState<'DAY' | 'NIGHT'>(row.shift_code === 'DAY' ? 'NIGHT' : 'DAY')
  const [otherUser, setOtherUser] = useState('')
  const [reason, setReason] = useState('')

  const target = useQuery({
    queryKey: ['roster-day', otherDate], queryFn: () => rosterApi.day(otherDate),
  })
  const targetRow = target.data?.find((r) => r.shift_code === otherShift)

  const save = useMutation({
    mutationFn: () => rosterApi.swap({
      first: { work_date: row.work_date, shift_code: row.shift_code, user_id: Number(mineUser) },
      second: { work_date: otherDate, shift_code: otherShift, user_id: Number(otherUser) },
      reason: reason.trim() || null,
    }),
    onSuccess: onDone, onError,
  })

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-start justify-center p-4"
         role="dialog" aria-modal="true" aria-label="근무 맞교환">
      <form className="bg-surface rounded shadow-lg border border-surface-border w-full max-w-lg mt-16 p-3 space-y-2"
            onSubmit={(e) => { e.preventDefault(); if (mineUser && otherUser) save.mutate() }}>
        <div className="flex items-center">
          <h3 className="font-medium flex-1">근무 맞교환</h3>
          <button type="button" className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={14} /></button>
        </div>

        <fieldset className="border border-surface-border rounded p-2">
          <legend className="text-sm text-ink-muted px-1">이 근무 · {row.work_date} {row.shift_label}</legend>
          <select className="input w-full" value={mineUser} onChange={(e) => setMineUser(e.target.value)}>
            {row.actual_user_ids.map((uid, i) => (
              <option key={uid} value={uid}>{row.actual_names[i]}</option>))}
          </select>
        </fieldset>

        <fieldset className="border border-surface-border rounded p-2 space-y-1.5">
          <legend className="text-sm text-ink-muted px-1">바꿀 근무</legend>
          <div className="flex gap-1.5">
            <input type="date" className="input flex-1" value={otherDate}
                   onChange={(e) => setOtherDate(e.target.value)} />
            <select className="input w-24" value={otherShift}
                    onChange={(e) => setOtherShift(e.target.value as 'DAY' | 'NIGHT')}>
              <option value="DAY">주간</option><option value="NIGHT">야간</option>
            </select>
          </div>
          <select className="input w-full" value={otherUser} onChange={(e) => setOtherUser(e.target.value)} required>
            <option value="">사람 고르기…</option>
            {(targetRow?.actual_user_ids ?? []).map((uid, i) => (
              <option key={uid} value={uid}>{targetRow!.actual_names[i]}</option>))}
          </select>
          {targetRow && targetRow.actual_user_ids.length === 0 && (
            <p className="text-sm text-ink-faint">그 날 그 교대에 배정된 사람이 없습니다.</p>)}
        </fieldset>

        <label className="block text-sm">
          사유
          <input className="input w-full mt-0.5" value={reason} maxLength={500}
                 onChange={(e) => setReason(e.target.value)} />
        </label>
        <p className="text-sm text-ink-faint">두 줄로 기록되며, 한쪽을 되돌리면 양쪽이 함께 되돌아갑니다.</p>

        <div className="flex justify-end gap-1 pt-1">
          <button type="button" className="btn btn-sm" onClick={onClose}>취소</button>
          <button type="submit" className="btn btn-sm btn-primary"
                  disabled={!mineUser || !otherUser || save.isPending}>맞교환</button>
        </div>
      </form>
    </div>
  )
}
