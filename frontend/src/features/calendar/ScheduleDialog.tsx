/**
 * 일정 만들기 · 보기 · 고치기 (FR-E, ASSUMPTIONS B-13).
 *
 * 하루 종일 일정은 화면에서 '마지막 날'을 보여주고(포함), 서버에는 그날 끝으로 보낸다 —
 * 서버는 끝을 포함하지 않는 자정 경계로 맞춘다. 반복은 고르는 방식으로 만들고 RRULE 로 보낸다.
 * 고칠 때는 바뀐 칸만, 지금 보고 있는 버전과 함께 보낸다(409 면 다시 불러온다).
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { addDays, format, parseISO } from 'date-fns'
import { Repeat, Trash2, X } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import {
  EVENT_TYPE_LABEL, SCHEDULE_QUERY_KEYS, scheduleApi,
  type EventType, type Schedule, type ScheduleChanges, type ScheduleInput,
} from '@/services/api/schedules'

type Freq = '' | 'DAILY' | 'WEEKLY' | 'MONTHLY'
interface Form {
  title: string
  event_type: EventType
  all_day: boolean
  start_date: string
  start_time: string
  end_date: string
  end_time: string
  owner_id: string
  company_id: string
  description: string
  freq: Freq
  interval: number
  byday: string[]
  end_mode: 'none' | 'count' | 'until'
  count: number
  until: string
}

const DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const DAY_KO: Record<string, string> = { MO: '월', TU: '화', WE: '수', TH: '목', FR: '금', SA: '토', SU: '일' }
const dayCode = (d: Date) => DAYS[(d.getDay() + 6) % 7]

export interface ScheduleDefaults {
  start?: Date
  allDay?: boolean
  handover?: { id: number; title: string }
  task?: { id: number; title: string }
}

function emptyForm(defaults?: ScheduleDefaults): Form {
  const start = defaults?.start ?? new Date(new Date().setMinutes(0, 0, 0) + 3600_000)
  const end = new Date(start.getTime() + 3600_000)
  return {
    title: '', event_type: 'GENERAL', all_day: !!defaults?.allDay,
    start_date: format(start, 'yyyy-MM-dd'), start_time: format(start, 'HH:mm'),
    end_date: format(defaults?.allDay ? start : end, 'yyyy-MM-dd'), end_time: format(end, 'HH:mm'),
    owner_id: '', company_id: '', description: '',
    freq: '', interval: 1, byday: [dayCode(start)], end_mode: 'none', count: 10, until: '',
  }
}

function fromSchedule(s: Schedule): Form {
  const start = parseISO(s.start_at)
  const end = parseISO(s.end_at)
  const parts = Object.fromEntries((s.recurrence_rule ?? '').split(';').filter(Boolean).map((p) => p.split('=')))
  const until = parts.UNTIL ? `${parts.UNTIL.slice(0, 4)}-${parts.UNTIL.slice(4, 6)}-${parts.UNTIL.slice(6, 8)}` : ''
  return {
    title: s.title, event_type: s.event_type, all_day: s.is_all_day,
    start_date: format(start, 'yyyy-MM-dd'), start_time: format(start, 'HH:mm'),
    end_date: format(s.is_all_day ? addDays(end, -1) : end, 'yyyy-MM-dd'), end_time: format(end, 'HH:mm'),
    owner_id: s.owner ? String(s.owner.id) : '', company_id: s.company ? String(s.company.id) : '',
    description: s.description ?? '',
    freq: (parts.FREQ ?? '') as Freq, interval: Number(parts.INTERVAL ?? 1),
    byday: parts.BYDAY ? parts.BYDAY.split(',') : [dayCode(start)],
    end_mode: parts.COUNT ? 'count' : parts.UNTIL ? 'until' : 'none',
    count: Number(parts.COUNT ?? 10), until,
  }
}

function rule(f: Form): string | null {
  if (!f.freq) return null
  const out = [`FREQ=${f.freq}`]
  if (f.interval > 1) out.push(`INTERVAL=${f.interval}`)
  if (f.freq === 'WEEKLY' && f.byday.length) out.push(`BYDAY=${DAYS.filter((d) => f.byday.includes(d)).join(',')}`)
  if (f.end_mode === 'count') out.push(`COUNT=${f.count}`)
  if (f.end_mode === 'until' && f.until) out.push(`UNTIL=${f.until.replaceAll('-', '')}`)
  return out.join(';')
}

function payload(f: Form): Required<Pick<ScheduleInput, 'title' | 'description' | 'event_type' | 'start_at' | 'end_at' | 'is_all_day' | 'owner_id' | 'company_id' | 'recurrence_rule'>> {
  return {
    title: f.title.trim() || null,
    description: f.description.trim() || null,
    event_type: f.event_type,
    is_all_day: f.all_day,
    start_at: f.all_day ? `${f.start_date}T00:00:00+09:00` : `${f.start_date}T${f.start_time}:00+09:00`,
    end_at: f.all_day ? `${f.end_date}T23:59:00+09:00` : `${f.end_date}T${f.end_time}:00+09:00`,
    owner_id: f.owner_id ? Number(f.owner_id) : null,
    company_id: f.company_id ? Number(f.company_id) : null,
    recurrence_rule: rule(f),
  }
}

export default function ScheduleDialog({ scheduleId, defaults, onClose }: {
  scheduleId?: number; defaults?: ScheduleDefaults; onClose: () => void
}) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const editing = scheduleId != null
  const { data: schedule, error: loadError } = useQuery({
    queryKey: ['schedule', scheduleId], queryFn: () => scheduleApi.get(scheduleId!), enabled: editing,
  })
  const { data: users } = useQuery({ queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000 })
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 60_000 })
  const [form, setForm] = useState<Form>(() => emptyForm(defaults))
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => { if (schedule) setForm(fromSchedule(schedule)) }, [schedule])
  useEffect(() => {
    // 뒤에 열린 상세 패널까지 Esc 로 닫히지 않게 먼저 받아서 멈춘다(capture)
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || confirmDelete) return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose, confirmDelete])

  const original = useMemo(() => (schedule ? payload(fromSchedule(schedule)) : null), [schedule])
  const readOnly = editing && !!schedule && !schedule.can_edit
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))
  const refresh = () => { for (const key of SCHEDULE_QUERY_KEYS) qc.invalidateQueries({ queryKey: [key] }) }
  const fail = (err: unknown) => {
    if (err instanceof ApiRequestError && err.status === 409) {
      setError('다른 사람이 먼저 이 일정을 바꿨습니다. 최신 내용으로 다시 불러왔습니다. 확인한 뒤 다시 저장하십시오.')
      qc.invalidateQueries({ queryKey: ['schedule', scheduleId] })
    } else {
      setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')
    }
  }

  const save = useMutation({
    mutationFn: async () => {
      const body = payload(form)
      if (!editing) {
        return scheduleApi.create({
          ...body, handover_id: defaults?.handover?.id ?? null, task_id: defaults?.task?.id ?? null,
        })
      }
      const changes: ScheduleChanges = {}
      for (const [key, value] of Object.entries(body) as [keyof typeof body, unknown][]) {
        if (JSON.stringify(value) !== JSON.stringify(original![key])) (changes as Record<string, unknown>)[key] = value
      }
      if ('title' in changes && !changes.title) delete changes.title
      if (!Object.keys(changes).length) return schedule!
      return scheduleApi.update(scheduleId!, schedule!.version_no, changes)
    },
    onSuccess: () => { refresh(); onClose() },
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: (reason: string) => scheduleApi.remove(scheduleId!, reason || undefined),
    onSuccess: () => { refresh(); onClose() },
    onError: fail,
  })

  const link = defaults?.handover ?? defaults?.task
  const linkedHandover = schedule?.handover ?? (defaults?.handover ? { ...defaults.handover, is_deleted: false } : null)
  const linkedTask = schedule?.task ?? (defaults?.task ? { ...defaults.task, is_deleted: false } : null)

  if (editing && loadError) {
    return (
      <Shell onClose={onClose} title="일정">
        <p className="text-ink-muted">일정을 찾을 수 없습니다(삭제되었을 수 있습니다).</p>
      </Shell>
    )
  }

  return (
    <Shell onClose={onClose} title={editing ? (readOnly ? '일정 보기' : '일정 고치기') : '일정 만들기'}
           badge={schedule ? `v${schedule.version_no}` : undefined}>
      <form className="space-y-2.5" onSubmit={(e) => { e.preventDefault(); setError(null); save.mutate() }}>
        {(linkedHandover || linkedTask) && (
          <p className="text-sm bg-brand-soft rounded px-2 py-1 space-x-2">
            {linkedHandover && <Link to={`/handovers?id=${linkedHandover.id}`} className="text-brand hover:underline">인수인계 #{linkedHandover.id} {linkedHandover.title}</Link>}
            {linkedTask && <Link to={`/tasks?id=${linkedTask.id}`} className="text-brand hover:underline">할일 #{linkedTask.id} {linkedTask.title}</Link>}
          </p>
        )}
        <fieldset disabled={readOnly || save.isPending} className="space-y-2.5">
          <Labeled label={link ? '제목' : '제목 *'}>
            <input className="input w-full" value={form.title} autoFocus={!editing}
                   placeholder={link ? link.title : '예: 방화벽 정기 점검'} onChange={(e) => set('title', e.target.value)} />
          </Labeled>
          <div className="grid grid-cols-2 gap-2">
            <Labeled label="유형">
              <select className="input w-full" value={form.event_type} onChange={(e) => set('event_type', e.target.value as EventType)}>
                {(Object.keys(EVENT_TYPE_LABEL) as EventType[]).map((t) => <option key={t} value={t}>{EVENT_TYPE_LABEL[t]}</option>)}
              </select>
            </Labeled>
            <label className="flex items-end gap-1.5 pb-1.5">
              <input type="checkbox" checked={form.all_day} onChange={(e) => set('all_day', e.target.checked)} />
              <span>하루 종일</span>
            </label>
            <Labeled label="시작">
              <div className="flex gap-1">
                <input type="date" className="input flex-1 min-w-0" value={form.start_date} required aria-label="시작일"
                       onChange={(e) => setForm((f) => ({
                         ...f, start_date: e.target.value,
                         end_date: f.end_date < e.target.value ? e.target.value : f.end_date,
                       }))} />
                {!form.all_day && <input type="time" className="input w-32" value={form.start_time} required aria-label="시작 시각"
                                         onChange={(e) => set('start_time', e.target.value)} />}
              </div>
            </Labeled>
            <Labeled label={form.all_day ? '마지막 날' : '끝'}>
              <div className="flex gap-1">
                <input type="date" className="input flex-1 min-w-0" value={form.end_date} required aria-label="끝나는 날"
                       min={form.start_date} onChange={(e) => set('end_date', e.target.value)} />
                {!form.all_day && <input type="time" className="input w-32" value={form.end_time} required aria-label="끝 시각"
                                         onChange={(e) => set('end_time', e.target.value)} />}
              </div>
            </Labeled>
            <Labeled label="담당자">
              <select className="input w-full" value={form.owner_id} onChange={(e) => set('owner_id', e.target.value)}>
                <option value="">{editing ? '(미지정)' : `나 (${me?.display_name ?? ''})`}</option>
                {(users ?? []).filter((u) => editing || u.id !== me?.id).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
              </select>
            </Labeled>
            <Labeled label="관계사">
              <select className="input w-full" value={form.company_id} onChange={(e) => set('company_id', e.target.value)}>
                <option value="">{link ? '(연결 대상과 같게)' : '(없음)'}</option>
                {(companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Labeled>
          </div>

          <fieldset className="border border-surface-border rounded px-2 py-1.5 space-y-1.5">
            <legend className="px-1 text-sm text-ink-muted inline-flex items-center gap-1"><Repeat size={11} /> 반복</legend>
            <div className="flex flex-wrap items-center gap-2">
              <select className="input" value={form.freq} onChange={(e) => set('freq', e.target.value as Freq)} aria-label="반복">
                <option value="">반복 안 함</option>
                <option value="DAILY">매일</option>
                <option value="WEEKLY">매주</option>
                <option value="MONTHLY">매월</option>
              </select>
              {form.freq && (
                <label className="inline-flex items-center gap-1">
                  <input type="number" min={1} max={99} className="input w-14" value={form.interval}
                         onChange={(e) => set('interval', Math.max(1, Math.min(99, Number(e.target.value) || 1)))} aria-label="간격" />
                  {form.freq === 'DAILY' ? '일' : form.freq === 'WEEKLY' ? '주' : '개월'}마다
                </label>
              )}
            </div>
            {form.freq === 'WEEKLY' && (
              <div className="flex gap-1" role="group" aria-label="요일">
                {DAYS.map((d) => (
                  <button key={d} type="button" aria-pressed={form.byday.includes(d)}
                          className={`btn btn-sm w-8 justify-center ${form.byday.includes(d) ? 'btn-primary' : ''}`}
                          onClick={() => set('byday', form.byday.includes(d) ? form.byday.filter((x) => x !== d) : [...form.byday, d])}>
                    {DAY_KO[d]}
                  </button>
                ))}
              </div>
            )}
            {form.freq && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-ink-muted">끝</span>
                <select className="input" value={form.end_mode} onChange={(e) => set('end_mode', e.target.value as Form['end_mode'])} aria-label="반복 끝">
                  <option value="none">계속</option>
                  <option value="count">횟수</option>
                  <option value="until">날짜까지</option>
                </select>
                {form.end_mode === 'count' && <input type="number" min={1} max={500} className="input w-20" value={form.count} aria-label="횟수"
                                                     onChange={(e) => set('count', Math.max(1, Math.min(500, Number(e.target.value) || 1)))} />}
                {form.end_mode === 'until' && <input type="date" className="input" value={form.until} min={form.start_date} required aria-label="반복 끝나는 날"
                                                     onChange={(e) => set('until', e.target.value)} />}
              </div>
            )}
            {schedule?.recurrence_text && <p className="text-xs text-ink-muted">지금: {schedule.recurrence_text}{schedule.series_end && ` (마지막 ${format(parseISO(schedule.series_end), 'yyyy-MM-dd')})`}</p>}
            {form.freq && <p className="text-xs text-ink-faint">반복 일정은 달력에서 끌어 옮길 수 없고, 여기서 시리즈 전체를 고칩니다.</p>}
          </fieldset>

          <Labeled label="내용">
            <textarea className="input w-full h-16 py-1 resize-y" value={form.description} onChange={(e) => set('description', e.target.value)} />
          </Labeled>
        </fieldset>

        {schedule && (
          <p className="text-xs text-ink-faint">
            만든 사람 {schedule.creator?.display_name ?? '-'} · {format(parseISO(schedule.created_at), 'MM/dd HH:mm')}
            {readOnly && ' · 담당자·만든 사람만 고칠 수 있습니다'}
          </p>
        )}
        {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}

        <div className="flex items-center gap-2">
          {editing && schedule?.can_edit && (
            <button type="button" className="btn text-state-urgent" onClick={() => setConfirmDelete(true)}><Trash2 size={12} /> 삭제</button>
          )}
          <span className="flex-1" />
          <button type="button" className="btn" onClick={onClose}>{readOnly ? '닫기' : '취소'}</button>
          {!readOnly && <button className="btn btn-primary" disabled={save.isPending || (editing && !schedule)}>{editing ? '저장' : '만들기'}</button>}
        </div>
      </form>

      {confirmDelete && schedule && (
        <ConfirmDialog title={`일정 '${schedule.title}' 을(를) 삭제합니다`} confirmLabel="삭제" danger busy={remove.isPending}
                       input={{ label: '사유', placeholder: '예: 점검 취소' }}
                       onCancel={() => setConfirmDelete(false)}
                       onConfirm={(reason) => { setConfirmDelete(false); remove.mutate(reason) }}>
          {schedule.recurrence_rule ? <p>반복 일정 전체({schedule.recurrence_text})가 지워집니다.</p> : <p>달력에서 사라지고, 기록(감사 로그)은 남습니다.</p>}
        </ConfirmDialog>
      )}
    </Shell>
  )
}

function Shell({ title, badge, onClose, children }: { title: string; badge?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/30 p-4" role="dialog" aria-modal="true" aria-labelledby="schedule-title">
      <div className="card w-[520px] max-w-full max-h-full overflow-auto shadow-xl p-4 space-y-2.5">
        <div className="flex items-center gap-2">
          <h2 id="schedule-title" className="font-medium text-md flex-1">{title}</h2>
          {badge && <span className="text-ink-faint text-sm tabular-nums">{badge}</span>}
          <button type="button" onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-0.5">
      <span className="text-ink-muted text-sm">{label}</span>
      {children}
    </label>
  )
}
