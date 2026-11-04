import { useQuery } from '@tanstack/react-query'
import { CalendarDays } from 'lucide-react'
import { Link } from 'react-router-dom'
import { scheduleApi } from '@/services/api/schedules'

const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' })
const clock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

function upcomingSchedules() {
  const now = new Date()
  const endDay = day.format(now.getTime() + 7 * 24 * 60 * 60 * 1000)
  return scheduleApi.calendar(now.toISOString(), `${endDay}T00:00:00+09:00`, ['schedule'], true)
}

function timeLabel(start: number, end: number, allDay: boolean) {
  const startDay = day.format(start)
  // 종일 일정의 종료 시각은 마지막 날 다음 날의 자정이다.
  const endDay = day.format(allDay ? end - 1 : end)
  if (allDay) return `${startDay}${endDay === startDay ? '' : ` ~ ${endDay}`} · 종일`
  return `${startDay} ${clock.format(start)} ~ ${endDay === startDay ? '' : `${endDay} `}${clock.format(end)}`
}

export default function UpcomingSchedules() {
  const calendar = useQuery({
    queryKey: ['calendar', 'dashboard', 'upcoming-mine'], queryFn: upcomingSchedules,
    staleTime: 30_000, refetchInterval: 60_000,
  })
  const now = Date.now()
  const rows = (calendar.data?.events ?? []).flatMap(event => {
    if (event.kind !== 'SCHEDULE' || !event.start || !event.end) return []
    const start = Date.parse(event.start)
    const end = Date.parse(event.end)
    return end > now ? [{ event, start, end }] : []
  }).sort((a, b) => a.start - b.start || a.event.id - b.event.id).slice(0, 3)

  return <section aria-labelledby="dashboard-calendar" className="card px-4 py-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="dashboard-calendar" className="flex items-center gap-2 text-lg font-semibold">
        <CalendarDays size={17} aria-hidden="true" className="text-brand" /> 내 일정
        <span className="text-sm font-normal text-ink-muted">오늘부터 7일</span>
      </h2>
      <div className="flex flex-wrap gap-2">
        <Link className="btn btn-sm" to="/schedules">전체 일정</Link>
        <Link className="btn btn-sm" to="/schedules?mine=1">내 일정</Link>
      </div>
    </div>
    {calendar.isPending && <p className="mt-2 text-sm text-ink-muted">일정을 불러오는 중…</p>}
    {calendar.isError && <p className="mt-2 text-sm">
      {calendar.data ? '일정 갱신에 실패했습니다. 마지막 조회 결과입니다.' : '일정을 불러오지 못했습니다.'}{' '}
      <button className="btn btn-sm" onClick={() => calendar.refetch()}>다시 시도</button>
    </p>}
    {rows.length > 0 && <ul className="mt-2 divide-y divide-surface-border">
      {rows.map(({ event, start, end }) => <li key={event.key}>
        <Link to={`/schedules?mine=1&id=${event.id}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded py-1.5 hover:bg-surface-sunken">
          <span className="break-words font-medium">{event.title}</span>
          <span className="text-sm tabular-nums text-ink-muted">{timeLabel(start, end, event.all_day)}</span>
          {start <= now && <span className="text-sm text-brand">진행 중</span>}
        </Link>
      </li>)}
    </ul>}
    {calendar.isSuccess && !rows.length && <p className="mt-2 text-sm text-ink-muted">앞으로 7일간 예정된 내 일정이 없습니다.</p>}
  </section>
}
