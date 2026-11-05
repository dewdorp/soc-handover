/**
 * 내 일정 (7일) + 일정마다 '내 알림'.
 *
 * 반복 일정은 앞의 세 회차까지만 나온다 — 매일 반복하는 점검 하나가 일주일치 목록을
 * 다 먹으면 정작 한 번뿐인 작업이 안 보인다. 가려진 회차 수는 숫자로 알려 준다.
 *
 * 알림은 **사람마다 따로**다. 받는 곳은 이미 쓰고 있는 알림함이며, 새 통로를 만들지 않는다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bell, BellOff } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { EVENT_TYPE_LABEL, scheduleApi, type MySchedule } from '@/services/api/schedules'

const PRESETS: { value: number | null; label: string }[] = [
  { value: null, label: '끄기' },
  { value: 0, label: '시작할 때' },
  { value: 10, label: '10분 전' },
  { value: 30, label: '30분 전' },
]

export default function MySchedules() {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['my-schedules'], queryFn: () => scheduleApi.mine(7, 3), staleTime: 30_000,
  })

  const setReminder = useMutation({
    mutationFn: ({ id, minutes }: { id: number; minutes: number | null }) =>
      scheduleApi.setReminder(id, minutes),
    onSuccess: () => { setError(null); qc.invalidateQueries({ queryKey: ['my-schedules'] }) },
    onError: (e) => setError(e instanceof ApiRequestError ? e.message : '알림을 바꾸지 못했습니다.'),
  })

  return (
    <section className="card min-w-0 p-4" aria-label="내 일정">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">내 일정 <span className="text-sm font-normal text-ink-muted">7일</span></h2>
        <Link className="text-sm text-brand hover:underline" to="/schedules?mine=1">달력에서 보기 →</Link>
      </div>

      {isPending && <p className="mt-3 text-ink-muted">불러오는 중…</p>}
      {isError && (
        <p className="mt-3 text-sm">
          내 일정을 불러오지 못했습니다.{' '}
          <button className="text-brand hover:underline" onClick={() => refetch()}>다시 시도</button>
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-state-urgent">{error}</p>}

      {data && (data.length
        ? (
          <ul className="mt-2 divide-y divide-surface-border">
            {data.map((row) => (
              <Row key={`${row.id}-${row.occurrence_no}`} row={row}
                   onPick={(minutes) => setReminder.mutate({ id: row.id, minutes })}
                   busy={setReminder.isPending} />
            ))}
          </ul>
        )
        : <p className="mt-3 text-ink-muted">앞으로 7일 안에 내 일정이 없습니다.</p>)}
    </section>
  )
}

function Row({ row, onPick, busy }: {
  row: MySchedule
  onPick: (minutes: number | null) => void
  busy: boolean
}) {
  const [custom, setCustom] = useState('')
  const preset = PRESETS.some((p) => p.value === row.reminder_minutes)
  const day = row.start_at.slice(5, 10)
  const time = row.is_all_day ? '종일' : row.start_at.slice(11, 16)

  return (
    <li className="py-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="tabular-nums text-sm text-ink-muted w-20 shrink-0">{day} {time}</span>
      <Link to={`/schedules?id=${row.id}`} className="flex-1 min-w-[10rem] font-medium hover:text-brand break-words">
        {row.title}
      </Link>
      <span className="text-sm text-ink-faint">{EVENT_TYPE_LABEL[row.event_type] ?? row.event_type}</span>
      {row.occurrence_no === 1 && row.more_occurrences > 0 && (
        <span className="text-xs text-ink-faint">+{row.more_occurrences}회 더</span>)}

      <span className="flex items-center gap-1">
        {row.reminder_minutes == null
          ? <BellOff size={12} className="text-ink-faint" aria-label="알림 꺼짐" />
          : <Bell size={12} className="text-brand" aria-label="알림 켜짐" />}
        <select className="input input-sm" aria-label={`${row.title} 내 알림`} disabled={busy}
                value={preset ? String(row.reminder_minutes ?? '') : 'custom'}
                onChange={(e) => {
                  if (e.target.value === 'custom') return
                  onPick(e.target.value === '' ? null : Number(e.target.value))
                }}>
          {PRESETS.map((p) => (
            <option key={String(p.value)} value={p.value === null ? '' : String(p.value)}>{p.label}</option>
          ))}
          <option value="custom">직접…</option>
        </select>
        {!preset && (
          <span className="flex items-center gap-1">
            <input className="input input-sm w-16" type="number" min={0} max={10080}
                   placeholder={String(row.reminder_minutes ?? '')} value={custom}
                   aria-label="몇 분 전"
                   onChange={(e) => setCustom(e.target.value)} />
            <span className="text-sm text-ink-faint">분 전</span>
            <button className="btn btn-sm" disabled={!custom || busy}
                    onClick={() => onPick(Number(custom))}>적용</button>
          </span>
        )}
      </span>
    </li>
  )
}
