/**
 * 일정 (/schedules, UI_STRUCTURE §6) — 팀 달력. 열린 일정은 주소에 둔다(?id=12) — 알림에서 바로 열린다.
 */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CalendarView from '@/features/calendar/CalendarView'
import ScheduleDialog, { type ScheduleDefaults } from '@/features/calendar/ScheduleDialog'

export default function CalendarPage() {
  const [params, setParams] = useSearchParams()
  const openId = params.get('id') ? Number(params.get('id')) : null
  const mine = params.get('mine') === '1'
  const [creating, setCreating] = useState<ScheduleDefaults | null>(null)

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: key !== 'id' })
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-3 pt-2">
        <h1 className="text-md font-medium">일정</h1>
      </div>
      <CalendarView mine={mine} onToggleMine={(v) => setParam('mine', v ? '1' : null)}
                    onOpenSchedule={(id) => setParam('id', String(id))}
                    onCreate={(start, allDay) => setCreating({ start, allDay })} />
      {openId != null && <ScheduleDialog key={openId} scheduleId={openId} onClose={() => setParam('id', null)} />}
      {creating && <ScheduleDialog defaults={creating} onClose={() => setCreating(null)} />}
    </div>
  )
}
