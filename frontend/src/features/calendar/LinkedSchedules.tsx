/**
 * 인수인계 · 할일에 딸린 일정 목록과 '일정 잡기'(FR-E-03). 비운 제목·관계사는 연결 대상에서 채운다.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { CalendarPlus, Repeat } from 'lucide-react'
import ScheduleDialog from '@/features/calendar/ScheduleDialog'
import { EVENT_TYPE_COLOR, EVENT_TYPE_LABEL, scheduleApi } from '@/services/api/schedules'

interface Props {
  handover?: { id: number; title: string }
  task?: { id: number; title: string }
  canCreate: boolean
}

export default function LinkedSchedules({ handover, task, canCreate }: Props) {
  const [openId, setOpenId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: handover ? ['handover-schedules', handover.id] : ['task-schedules', task!.id],
    queryFn: () => (handover ? scheduleApi.forHandover(handover.id) : scheduleApi.forTask(task!.id)),
  })

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <h3 className="text-ink-muted text-sm flex-1">일정 {data?.length ? <span className="tabular-nums">{data.length}</span> : null}</h3>
        {canCreate && (
          <button className="btn btn-sm" onClick={() => setCreating(true)}><CalendarPlus size={12} /> 일정 잡기</button>
        )}
      </div>
      <ul className="space-y-1">
        {(data ?? []).map((s) => {
          const start = parseISO(s.start_at)
          const color = s.color ?? EVENT_TYPE_COLOR[s.event_type]
          return (
            <li key={s.id}>
              <button className="card w-full px-2 py-1.5 flex items-center gap-2 text-left hover:border-brand/50"
                      style={{ borderLeft: `3px solid ${color}` }} onClick={() => setOpenId(s.id)}>
                <span className="text-sm tabular-nums shrink-0 text-ink-muted">
                  {format(start, s.is_all_day ? 'MM/dd' : 'MM/dd HH:mm')}
                </span>
                <span className="flex-1 truncate">{s.title}</span>
                {s.recurrence_text && <span className="text-xs text-ink-faint shrink-0 inline-flex items-center gap-0.5"><Repeat size={9} />{s.recurrence_text}</span>}
                <span className="text-xs text-ink-muted shrink-0">{EVENT_TYPE_LABEL[s.event_type]} · {s.owner?.display_name ?? '(미지정)'}</span>
              </button>
            </li>
          )
        })}
        {!isLoading && data?.length === 0 && <li className="text-ink-faint text-sm">잡힌 일정이 없습니다.</li>}
      </ul>
      {openId != null && <ScheduleDialog key={openId} scheduleId={openId} onClose={() => setOpenId(null)} />}
      {creating && <ScheduleDialog defaults={{ handover, task }} onClose={() => setCreating(false)} />}
    </div>
  )
}
