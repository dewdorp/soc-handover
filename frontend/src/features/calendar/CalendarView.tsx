/**
 * 달력 (FR-E-01·03·04) — 월 · 주 · 일 보기, 일정 + 할일 마감 + 인수인계 수행일 레이어.
 *
 * 끌어서 옮길 수 있는 것은 '고칠 수 있고 반복이 아닌 일정'뿐이다(can_move). 주·일 보기에서는
 * 30분 칸에 붙고, 월 보기에서는 날짜만 바뀐다(시각 유지). 서버는 길이를 유지하고 감사에 남긴다.
 * 할일·인수인계는 누르면 원래 화면으로 간다(마감·수행일은 각 상세에서 바꾼다).
 * 시각 계산은 브라우저 시간대가 KST 라는 전제다(앱 전체가 Asia/Seoul 고정).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  addDays, addMonths, addWeeks, differenceInCalendarDays, eachDayOfInterval, endOfMonth, endOfWeek,
  format, isSameDay, isSameMonth, parseISO, startOfDay, startOfMonth, startOfWeek,
} from 'date-fns'
import { ko as KO } from 'date-fns/locale'
import { ChevronLeft, ChevronRight, ClipboardList, FileText, Plus, Repeat, X } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import {
  EVENT_TYPE_COLOR, EVENT_TYPE_LABEL, SCHEDULE_QUERY_KEYS, kstIso, scheduleApi,
  type CalendarEvent, type CalendarLayer,
} from '@/services/api/schedules'

export type CalendarMode = 'month' | 'week' | 'day'
const HOUR_PX = 40
const SLOT_MIN = 30
const WEEK = { weekStartsOn: 1 as const }
const LAYERS: { key: CalendarLayer; label: string }[] = [
  { key: 'schedule', label: '일정' }, { key: 'task', label: '할일 마감' }, { key: 'handover', label: '인수인계 수행일' },
]

interface Props {
  mine: boolean
  onToggleMine?: (mine: boolean) => void
  onOpenSchedule: (id: number) => void
  onCreate: (start: Date, allDay: boolean) => void
}

export default function CalendarView({ mine, onToggleMine, onOpenSchedule, onCreate }: Props) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [mode, setMode] = useState<CalendarMode>('month')
  const [cursor, setCursor] = useState(() => startOfDay(new Date()))
  const [layers, setLayers] = useState<CalendarLayer[]>(['schedule', 'task', 'handover'])
  const [dragging, setDragging] = useState<CalendarEvent | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const days = useMemo(() => {
    if (mode === 'month') {
      return eachDayOfInterval({ start: startOfWeek(startOfMonth(cursor), WEEK), end: endOfWeek(endOfMonth(cursor), WEEK) })
    }
    if (mode === 'week') return eachDayOfInterval({ start: startOfWeek(cursor, WEEK), end: endOfWeek(cursor, WEEK) })
    return [cursor]
  }, [mode, cursor])
  const rangeStart = days[0]
  const rangeEnd = addDays(days[days.length - 1], 1)

  const { data, isFetching } = useQuery({
    queryKey: ['calendar', kstIso(rangeStart), kstIso(rangeEnd), layers.join(','), mine],
    queryFn: () => scheduleApi.calendar(kstIso(rangeStart), kstIso(rangeEnd), layers, mine),
    enabled: layers.length > 0,
  })
  const events = layers.length ? data?.events ?? [] : []

  const move = useMutation({
    mutationFn: ({ ev, start }: { ev: CalendarEvent; start: Date }) =>
      scheduleApi.move(ev.id, ev.version_no!, kstIso(start)),
    onSuccess: () => setNotice(null),
    onError: (err) => setNotice(err instanceof ApiRequestError && err.status === 409
      ? '다른 사람이 먼저 이 일정을 바꿨습니다. 최신 달력으로 다시 불러왔습니다.'
      : err instanceof ApiRequestError ? err.message : '옮기지 못했습니다.'),
    onSettled: () => { for (const k of SCHEDULE_QUERY_KEYS) qc.invalidateQueries({ queryKey: [k] }) },
  })

  /** 월 보기·종일 칸에 놓기: 날짜만 바꾸고 시각은 그대로. */
  const dropOnDay = (day: Date) => {
    const ev = dragging
    setDragging(null)
    if (!ev?.start) return
    const start = parseISO(ev.start)
    const delta = differenceInCalendarDays(day, start)
    if (delta !== 0) move.mutate({ ev, start: addDays(start, delta) })
  }
  /** 주·일 보기 시간 칸에 놓기: 30분 칸의 시작으로. */
  const dropAtTime = (day: Date, minutes: number) => {
    const ev = dragging
    setDragging(null)
    if (!ev?.start) return
    if (ev.all_day) { dropOnDay(day); return }
    const start = new Date(day.getTime() + minutes * 60_000)
    if (start.getTime() !== parseISO(ev.start).getTime()) move.mutate({ ev, start })
  }

  const open = (ev: CalendarEvent) => {
    if (ev.kind === 'SCHEDULE') onOpenSchedule(ev.id)
    else if (ev.kind === 'TASK') navigate(`/tasks?id=${ev.id}`)
    else navigate(`/handovers?id=${ev.id}`)
  }
  const step = (dir: 1 | -1) => setCursor((c) => mode === 'month' ? addMonths(c, dir) : mode === 'week' ? addWeeks(c, dir) : addDays(c, dir))
  const title = mode === 'month' ? format(cursor, 'yyyy년 M월')
    : mode === 'week' ? `${format(days[0], 'yyyy년 M월 d일')} ~ ${format(days[6], isSameMonth(days[0], days[6]) ? 'd일' : 'M월 d일')}`
      : format(cursor, 'yyyy년 M월 d일 (EEE)', { locale: KO })

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-surface-border">
        <button className="btn btn-sm" onClick={() => setCursor(startOfDay(new Date()))}>오늘</button>
        <button className="btn btn-sm" onClick={() => step(-1)} aria-label="이전"><ChevronLeft size={12} /></button>
        <button className="btn btn-sm" onClick={() => step(1)} aria-label="다음"><ChevronRight size={12} /></button>
        <h2 className="font-medium text-md min-w-[9rem]">{title}</h2>
        <div className="flex gap-1" role="radiogroup" aria-label="보기">
          {(['month', 'week', 'day'] as const).map((m) => (
            <button key={m} role="radio" aria-checked={mode === m} className={`btn btn-sm ${mode === m ? 'btn-primary' : ''}`}
                    onClick={() => setMode(m)}>{{ month: '월', week: '주', day: '일' }[m]}</button>
          ))}
        </div>
        <span className="flex-1" />
        <div className="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="레이어">
          {LAYERS.map((l) => (
            <label key={l.key} className="inline-flex items-center gap-1">
              <input type="checkbox" checked={layers.includes(l.key)}
                     onChange={(e) => setLayers((ls) => e.target.checked ? [...ls, l.key] : ls.filter((x) => x !== l.key))} />
              {l.label}
            </label>
          ))}
          {onToggleMine && (
            <label className="inline-flex items-center gap-1 ml-1">
              <input type="checkbox" checked={mine} onChange={(e) => onToggleMine(e.target.checked)} /> 내 것만
            </label>
          )}
        </div>
        <button className="btn btn-sm btn-primary" onClick={() => onCreate(new Date(cursor.getTime() + 9 * 3600_000), false)}>
          <Plus size={12} /> 일정
        </button>
      </div>

      {(notice || data?.truncated) && (
        <p role="alert" className="mx-3 mt-2 text-sm text-state-check bg-amber-50 border border-amber-200 rounded px-2 py-1 flex items-center gap-2">
          <span className="flex-1">{notice ?? '표시할 항목이 너무 많아 일부만 보입니다. 레이어를 줄이거나 주 보기를 쓰십시오.'}</span>
          {notice && <button onClick={() => setNotice(null)} aria-label="안내 닫기"><X size={12} /></button>}
        </p>
      )}
      {isFetching && !data && <p className="p-3 text-ink-faint">불러오는 중…</p>}

      {mode === 'month'
        ? <MonthGrid days={days} cursor={cursor} events={events} dragging={dragging} setDragging={setDragging}
                     onDropDay={dropOnDay} onOpen={open} onCreate={onCreate}
                     onMore={(d) => { setCursor(d); setMode('day') }} />
        : <TimeGrid days={days} events={events} dragging={dragging} setDragging={setDragging}
                    onDropDay={dropOnDay} onDropTime={dropAtTime} onOpen={open} onCreate={onCreate} />}
    </div>
  )
}

// ------------------------------------------------------------------ 공통


function eventsOn(day: Date, events: CalendarEvent[]): CalendarEvent[] {
  const dayStart = startOfDay(day).getTime()
  const dayEnd = addDays(startOfDay(day), 1).getTime()
  const key = format(day, 'yyyy-MM-dd')
  return events.filter((e) => e.kind === 'SCHEDULE'
    ? parseISO(e.start!).getTime() < dayEnd && parseISO(e.end!).getTime() > dayStart
    : e.day === key)
}

function colorOf(ev: CalendarEvent): string {
  return ev.color ?? (ev.event_type ? EVENT_TYPE_COLOR[ev.event_type] : '#475569')
}

interface ChipProps {
  ev: CalendarEvent
  showTime?: boolean
  setDragging: (ev: CalendarEvent | null) => void
  onOpen: (ev: CalendarEvent) => void
  dragging: boolean
}

function Chip({ ev, showTime, setDragging, onOpen, dragging }: ChipProps) {
  const base = 'w-full text-left truncate rounded px-1 text-xs leading-5'
  const tip = ev.kind === 'SCHEDULE'
    ? `${ev.title}${ev.event_type ? ` · ${EVENT_TYPE_LABEL[ev.event_type]}` : ''}${ev.owner ? ` · ${ev.owner}` : ''}`
      + (ev.recurring ? ' · 반복(상세에서 고침)' : ev.can_move ? ' · 끌어서 옮기기' : '')
    : `${ev.kind === 'TASK' ? '할일 마감' : '인수인계 수행일'} · ${ev.title}${ev.status ? ` · ${ev.status}` : ''}`
  if (ev.kind !== 'SCHEDULE') {
    const Icon = ev.kind === 'TASK' ? ClipboardList : FileText
    return (
      <button type="button" title={tip} onClick={(e) => { e.stopPropagation(); onOpen(ev) }}
              className={`${base} border border-surface-border bg-surface inline-flex items-center gap-1 ${ev.is_done ? 'line-through text-ink-faint' : ev.is_overdue ? 'text-state-urgent' : 'text-ink-muted'}`}>
        <Icon size={10} className="shrink-0" /><span className="truncate">{ev.title}</span>
      </button>
    )
  }
  const color = colorOf(ev)
  return (
    // 끌 수 있는 것은 button 이 아니라 div — Firefox 는 button 을 끌지 못한다(할일 보드 카드와 같은 방식)
    <div role="button" tabIndex={0} title={tip} draggable={ev.can_move}
         onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', ev.key); setDragging(ev) }}
         onDragEnd={() => setDragging(null)}
         onClick={(e) => { e.stopPropagation(); onOpen(ev) }}
         onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onOpen(ev) } }}
         style={{ backgroundColor: `${color}1f`, borderLeft: `3px solid ${color}` }}
         className={`${base} flex items-center gap-1 cursor-pointer ${ev.can_move ? 'cursor-grab' : ''} ${dragging ? 'opacity-40' : ''}`}>
      {ev.recurring && <Repeat size={9} className="shrink-0" />}
      {showTime && !ev.all_day && <span className="tabular-nums shrink-0">{format(parseISO(ev.start!), 'HH:mm')}</span>}
      <span className="truncate">{ev.title}</span>
    </div>
  )
}

// ------------------------------------------------------------------ 월

function MonthGrid({ days, cursor, events, dragging, setDragging, onDropDay, onOpen, onCreate, onMore }: {
  days: Date[]; cursor: Date; events: CalendarEvent[]; dragging: CalendarEvent | null
  setDragging: (ev: CalendarEvent | null) => void; onDropDay: (d: Date) => void
  onOpen: (ev: CalendarEvent) => void; onCreate: (start: Date, allDay: boolean) => void; onMore: (d: Date) => void
}) {
  const [over, setOver] = useState<string | null>(null)
  const today = new Date()
  const MAX = 4
  return (
    <div className="flex-1 min-h-0 flex flex-col p-3">
      <div className="grid grid-cols-7 text-center text-sm text-ink-muted pb-1">
        {['월', '화', '수', '목', '금', '토', '일'].map((d, i) => (
          <div key={d} className={i === 5 ? 'text-state-open' : i === 6 ? 'text-state-urgent' : ''}>{d}</div>
        ))}
      </div>
      <div className="flex-1 min-h-0 grid grid-cols-7 auto-rows-fr border-l border-t border-surface-border bg-surface">
        {days.map((day) => {
          const key = format(day, 'yyyy-MM-dd')
          const list = eventsOn(day, events).sort(sortEvents)
          const dim = !isSameMonth(day, cursor)
          return (
            <div key={key}
                 onClick={() => onCreate(new Date(day.getTime() + 9 * 3600_000), false)}
                 onDragOver={(e) => { if (dragging) { e.preventDefault(); if (over !== key) setOver(key) } }}
                 onDragLeave={() => setOver((o) => (o === key ? null : o))}
                 onDrop={(e) => { e.preventDefault(); setOver(null); onDropDay(day) }}
                 className={`min-h-[5.5rem] border-r border-b border-surface-border p-1 space-y-0.5 overflow-hidden cursor-pointer
                             ${dim ? 'bg-surface-sunken/60' : ''} ${over === key ? 'ring-2 ring-inset ring-brand bg-brand-soft' : ''}`}
                 aria-label={format(day, 'M월 d일')}>
              <div className={`text-xs tabular-nums ${isSameDay(day, today) ? 'inline-grid place-items-center w-5 h-5 rounded-full bg-brand text-white' : dim ? 'text-ink-faint' : ''}`}>
                {format(day, 'd')}
              </div>
              {list.slice(0, MAX).map((ev) => (
                <Chip key={ev.key} ev={ev} showTime setDragging={setDragging} onOpen={onOpen} dragging={dragging?.key === ev.key} />
              ))}
              {list.length > MAX && (
                <button type="button" className="text-xs text-brand hover:underline" onClick={(e) => { e.stopPropagation(); onMore(day) }}>
                  +{list.length - MAX} 더보기
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function sortEvents(a: CalendarEvent, b: CalendarEvent): number {
  const rank = (e: CalendarEvent) => (e.kind === 'SCHEDULE' ? (e.all_day ? 0 : 1) : e.kind === 'TASK' ? 2 : 3)
  if (rank(a) !== rank(b)) return rank(a) - rank(b)
  return (a.start ?? '').localeCompare(b.start ?? '') || a.title.localeCompare(b.title)
}

// ------------------------------------------------------------------ 주 · 일

interface Placed { ev: CalendarEvent; top: number; height: number; lane: number; lanes: number }

/** 하루 안의 시간 일정 배치 — 겹치는 묶음마다 칸을 나눈다. */
function layout(day: Date, events: CalendarEvent[]): Placed[] {
  const dayStart = startOfDay(day).getTime()
  const dayEnd = dayStart + 86_400_000
  const items = events
    .filter((e) => e.kind === 'SCHEDULE' && !e.all_day)
    .map((ev) => {
      const s = Math.max(parseISO(ev.start!).getTime(), dayStart)
      const e = Math.min(parseISO(ev.end!).getTime(), dayEnd)
      return { ev, s, e }
    })
    .filter((x) => x.e > x.s)
    .sort((a, b) => a.s - b.s || b.e - a.e)
  const placed: Placed[] = []
  let group: { item: typeof items[number]; lane: number }[] = []
  let groupEnd = 0
  const flush = () => {
    const lanes = Math.max(1, ...group.map((g) => g.lane + 1))
    for (const g of group) {
      placed.push({
        ev: g.item.ev, lane: g.lane, lanes,
        top: ((g.item.s - dayStart) / 3_600_000) * HOUR_PX,
        height: Math.max(18, ((g.item.e - g.item.s) / 3_600_000) * HOUR_PX - 2),
      })
    }
    group = []
  }
  for (const item of items) {
    if (group.length && item.s >= groupEnd) flush()
    const used = new Set(group.filter((g) => g.item.e > item.s).map((g) => g.lane))
    let lane = 0
    while (used.has(lane)) lane += 1
    group.push({ item, lane })
    groupEnd = Math.max(groupEnd, item.e)
  }
  if (group.length) flush()
  return placed
}

function TimeGrid({ days, events, dragging, setDragging, onDropDay, onDropTime, onOpen, onCreate }: {
  days: Date[]; events: CalendarEvent[]; dragging: CalendarEvent | null
  setDragging: (ev: CalendarEvent | null) => void; onDropDay: (d: Date) => void
  onDropTime: (d: Date, minutes: number) => void; onOpen: (ev: CalendarEvent) => void
  onCreate: (start: Date, allDay: boolean) => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [overSlot, setOverSlot] = useState<string | null>(null)
  const today = new Date()
  useEffect(() => { if (scroller.current) scroller.current.scrollTop = 8 * HOUR_PX }, [])
  const slotFrom = (e: React.DragEvent | React.MouseEvent, col: HTMLElement) => {
    const y = e.clientY - col.getBoundingClientRect().top
    return Math.max(0, Math.min(24 * 60 - SLOT_MIN, Math.floor((y / HOUR_PX) * 60 / SLOT_MIN) * SLOT_MIN))
  }
  const cols = `3.5rem repeat(${days.length}, minmax(0, 1fr))`

  return (
    // 머리글·종일 칸을 시간 칸과 같은 스크롤 영역에 두고 위에 붙인다 — 스크롤바 폭만큼 열이 어긋나지 않게
    <div className="flex-1 min-h-0 flex flex-col p-3">
      <div ref={scroller} className="flex-1 min-h-0 overflow-y-auto bg-surface border border-surface-border rounded">
      <div className="sticky top-0 z-10 bg-surface">
      <div className="grid border-b border-surface-border" style={{ gridTemplateColumns: cols }}>
        <div />
        {days.map((day) => (
          <div key={day.toISOString()} className={`text-center text-sm py-1 ${isSameDay(day, today) ? 'text-brand font-medium' : 'text-ink-muted'}`}>
            {format(day, 'M/d (EEE)', { locale: KO })}
          </div>
        ))}
      </div>
      {/* 하루 종일 · 할일 · 인수인계 */}
      <div className="grid border-b border-surface-border bg-surface" style={{ gridTemplateColumns: cols }}>
        <div className="text-xs text-ink-faint text-right pr-1 pt-1">종일</div>
        {days.map((day) => {
          const list = eventsOn(day, events).filter((e) => e.kind !== 'SCHEDULE' || e.all_day).sort(sortEvents)
          return (
            <div key={day.toISOString()} className="border-l border-surface-border p-0.5 space-y-0.5 min-h-[1.75rem] max-h-28 overflow-y-auto"
                 onDragOver={(e) => { if (dragging) e.preventDefault() }}
                 onDrop={(e) => { e.preventDefault(); onDropDay(day) }}
                 onClick={() => onCreate(day, true)}>
              {list.map((ev) => <Chip key={ev.key} ev={ev} setDragging={setDragging} onOpen={onOpen} dragging={dragging?.key === ev.key} />)}
            </div>
          )
        })}
      </div>
      </div>
        <div className="grid relative" style={{ gridTemplateColumns: cols, height: 24 * HOUR_PX }}>
          <div className="relative">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="absolute right-1 text-xs text-ink-faint tabular-nums" style={{ top: h * HOUR_PX - 6 }}>
                {h ? `${String(h).padStart(2, '0')}:00` : ''}
              </div>
            ))}
          </div>
          {days.map((day) => {
            const key = format(day, 'yyyy-MM-dd')
            return (
              <div key={key} className={`relative border-l border-surface-border ${isSameDay(day, today) ? 'bg-brand-soft/40' : ''}`}
                   onClick={(e) => onCreate(new Date(startOfDay(day).getTime() + slotFrom(e, e.currentTarget) * 60_000), false)}
                   onDragOver={(e) => {
                     if (!dragging) return
                     e.preventDefault()
                     const slot = `${key}@${slotFrom(e, e.currentTarget)}`
                     if (slot !== overSlot) setOverSlot(slot)
                   }}
                   onDragLeave={() => setOverSlot(null)}
                   onDrop={(e) => { e.preventDefault(); setOverSlot(null); onDropTime(startOfDay(day), slotFrom(e, e.currentTarget)) }}>
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} className="absolute inset-x-0 border-t border-surface-border/70" style={{ top: h * HOUR_PX }} />
                ))}
                {overSlot?.startsWith(`${key}@`) && (
                  <div className="absolute inset-x-0 bg-brand/20 border-t-2 border-brand pointer-events-none"
                       style={{ top: (Number(overSlot.split('@')[1]) / 60) * HOUR_PX, height: (SLOT_MIN / 60) * HOUR_PX }} />
                )}
                {layout(day, events).map(({ ev, top, height, lane, lanes }) => (
                  <div key={ev.key} className="absolute px-0.5" style={{ top, height, left: `${(lane / lanes) * 100}%`, width: `${100 / lanes}%` }}>
                    <TimedBlock ev={ev} height={height} setDragging={setDragging} onOpen={onOpen} dragging={dragging?.key === ev.key} />
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function TimedBlock({ ev, height, setDragging, onOpen, dragging }: ChipProps & { height: number }) {
  const color = colorOf(ev)
  return (
    <div role="button" tabIndex={0} draggable={ev.can_move}
         title={`${ev.title} · ${format(parseISO(ev.start!), 'HH:mm')}~${format(parseISO(ev.end!), 'HH:mm')}${ev.recurring ? ' · 반복' : ''}`}
         onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', ev.key); setDragging(ev) }}
         onDragEnd={() => setDragging(null)}
         onClick={(e) => { e.stopPropagation(); onOpen(ev) }}
         onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onOpen(ev) } }}
         style={{ backgroundColor: `${color}26`, borderLeft: `3px solid ${color}`, height }}
         className={`w-full rounded text-left text-xs px-1 overflow-hidden cursor-pointer ${ev.can_move ? 'cursor-grab' : ''} ${dragging ? 'opacity-40' : ''}`}>
      <div className="tabular-nums text-ink-muted inline-flex items-center gap-0.5">
        {ev.recurring && <Repeat size={9} />}{format(parseISO(ev.start!), 'HH:mm')}
      </div>
      <div className="font-medium leading-tight break-words">{ev.title}</div>
    </div>
  )
}
