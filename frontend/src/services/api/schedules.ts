/** 일정 · 달력 API (API.md §5, ASSUMPTIONS B-13). 시각은 시간대가 붙은 ISO, 끝은 포함하지 않는다. */
import { api } from '@/services/api/client'
import type { Company, UserBrief } from '@/types/api'

export type EventType = 'GENERAL' | 'WORK_PLANNED' | 'INSPECTION' | 'MEETING' | 'SECURITY_WORK' | 'RECURRING'
export type CalendarLayer = 'schedule' | 'task' | 'handover'

export interface Schedule {
  id: number
  title: string
  description: string | null
  event_type: EventType
  start_at: string
  end_at: string
  is_all_day: boolean
  company: Company | null
  handover: { id: number; title: string; is_deleted: boolean } | null
  task: { id: number; title: string; is_deleted: boolean } | null
  owner: UserBrief | null
  creator: UserBrief | null
  recurrence_rule: string | null
  recurrence_text: string | null
  series_end: string | null
  color: string | null
  version_no: number
  can_edit: boolean
  created_at: string
  updated_at: string
}

export interface ScheduleInput {
  title?: string | null
  description?: string | null
  event_type?: EventType
  start_at: string
  end_at?: string | null
  is_all_day?: boolean
  company_id?: number | null
  handover_id?: number | null
  task_id?: number | null
  owner_id?: number | null
  recurrence_rule?: string | null
  color?: string | null
}

export type ScheduleChanges = Partial<Omit<ScheduleInput, 'handover_id' | 'task_id'>>

export interface CalendarEvent {
  key: string
  kind: 'SCHEDULE' | 'TASK' | 'HANDOVER'
  id: number
  title: string
  start: string | null
  end: string | null
  day: string | null
  all_day: boolean
  event_type: EventType | null
  color: string | null
  company: string | null
  status: string | null
  is_done: boolean
  is_overdue: boolean
  recurring: boolean
  owner: string | null
  can_move: boolean
  version_no: number | null
}

export interface CalendarData {
  start: string
  end: string
  events: CalendarEvent[]
  truncated: boolean
}

export interface MySchedule {
  id: number
  title: string
  event_type: EventType
  start_at: string
  end_at: string
  is_all_day: boolean
  company: string | null
  handover_id: number | null
  task_id: number | null
  recurrence_rule: string | null
  reminder_minutes: number | null
  occurrence_no: number
  more_occurrences: number
}

export const scheduleApi = {
  mine: (days = 7, perSeries = 3) =>
    api.get<MySchedule[]>(`/schedules/mine?days=${days}&per_series=${perSeries}`),
  setReminder: (id: number, minutes: number | null) =>
    api.put<{ schedule_id: number; minutes_before: number | null }>(
      `/schedules/${id}/reminder`, { minutes_before: minutes }),
  calendar: (start: string, end: string, layers: CalendarLayer[], mine: boolean) =>
    api.get<CalendarData>(`/calendar?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
      + `&layers=${layers.join(',')}&mine=${mine}`),
  get: (id: number) => api.get<Schedule>(`/schedules/${id}`),
  create: (body: ScheduleInput) => api.post<Schedule>('/schedules', body),
  update: (id: number, expected_version: number, changes: ScheduleChanges) =>
    api.patch<Schedule>(`/schedules/${id}`, { expected_version, ...changes }),
  move: (id: number, expected_version: number, start_at: string, end_at?: string | null) =>
    api.patch<Schedule>(`/schedules/${id}/move`, { expected_version, start_at, end_at: end_at ?? null }),
  remove: (id: number, reason?: string) => api.delete<void>(`/schedules/${id}`, reason ? { reason } : undefined),
  forHandover: (handoverId: number) => api.get<Schedule[]>(`/handovers/${handoverId}/schedules`),
  forTask: (taskId: number) => api.get<Schedule[]>(`/tasks/${taskId}/schedules`),

  /** 그 날 돌아야 하는 '점검' 종류 반복 일정과 완료 여부 */
  inspections: (day?: string) =>
    api.get<Inspection[]>(`/schedules/inspections${day ? `?day=${day}` : ''}`),
  completeInspection: (id: number, day: string, note?: string) =>
    api.post<Inspection>(`/schedules/${id}/completions`, { occurrence_date: day, note: note ?? null }),
  reopenInspection: (id: number, day: string) =>
    api.delete<void>(`/schedules/${id}/completions/${day}`),
}

/** 정기 점검 한 회차 */
export interface Inspection {
  schedule_id: number
  title: string
  occurrence_date: string
  start_at: string
  company: string | null
  owner_id: number | null
  owner_name: string | null
  recurrence_text: string | null
  is_done: boolean
  done_by_name: string | null
  done_at: string | null
  note: string | null
  is_mine: boolean
}

export const EVENT_TYPE_LABEL: Record<EventType, string> = {
  GENERAL: '일반', WORK_PLANNED: '작업예정', INSPECTION: '점검', MEETING: '회의',
  SECURITY_WORK: '보안작업', RECURRING: '반복업무',
}

/** 유형별 기본 색 — 사용자가 색을 정하지 않은 일정에 쓴다. */
export const EVENT_TYPE_COLOR: Record<EventType, string> = {
  GENERAL: '#2563eb', WORK_PLANNED: '#0891b2', INSPECTION: '#d97706', MEETING: '#7c3aed',
  SECURITY_WORK: '#dc2626', RECURRING: '#16a34a',
}

export const SCHEDULE_QUERY_KEYS = ['calendar', 'schedule', 'handover-schedules', 'task-schedules', 'my-work', 'timeline', 'handover']

/** KST 오프셋을 붙인 ISO — 서버와 화면이 같은 시각을 보게. */
export function kstIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00+09:00`
}
