/**
 * 내 업무 (FR-D-01·02, UI_STRUCTURE §6) — 내 할일 + 내 담당 인수인계 + 내가 확인할 인수인계.
 *
 * 버킷 규칙은 서버(ASSUMPTIONS B-12)가 정한다. 여기서는 건수 탭과 목록만 그린다.
 * 할일은 이 화면에서 바로 열고, 인수인계는 인수인계 화면, 확인할 건은 인수 확인함으로 보낸다.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CalendarDays, CheckCircle2, ClipboardList, FileText, Plus } from 'lucide-react'
import TaskBoard from '@/features/tasks/TaskBoard'
import TaskCreateDialog from '@/features/tasks/TaskCreateDialog'
import TaskDrawer from '@/features/tasks/TaskDrawer'
import {
  STATUS_LABEL, taskApi, type MyWorkBucket, type MyWorkItem, type MyWorkSource, type TaskStatus,
} from '@/services/api/tasks'

const BUCKETS: { key: MyWorkBucket; label: string; tone?: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'today', label: '오늘' },
  { key: 'overdue', label: '지연', tone: 'text-state-urgent' },
  { key: 'this_week', label: '이번주' },
  { key: 'upcoming', label: '예정' },
  { key: 'need_ack', label: '확인필요', tone: 'text-state-check' },
  { key: 'waiting', label: '대기' },
  { key: 'done', label: '완료', tone: 'text-state-done' },
]
const SOURCES: { key: MyWorkSource; label: string }[] = [
  { key: 'all', label: '전체' }, { key: 'task', label: '할일' },
  { key: 'handover', label: '담당 인수인계' }, { key: 'ack', label: '확인할 인수인계' },
]
const KIND = {
  TASK: { label: '할일', icon: ClipboardList, tone: 'text-brand' },
  HANDOVER: { label: '인수인계', icon: FileText, tone: 'text-ink-muted' },
  ACK: { label: '확인', icon: CheckCircle2, tone: 'text-state-check' },
} as const

export default function MyWorkPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const bucket = (params.get('bucket') as MyWorkBucket | null) ?? 'all'
  const source = (params.get('source') as MyWorkSource | null) ?? 'all'
  const view = params.get('view') === 'board' ? 'board' : 'list'
  const openId = params.get('task') ? Number(params.get('task')) : null
  const [creating, setCreating] = useState(false)

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: key !== 'task' })
  }

  const { data, isFetching } = useQuery({
    queryKey: ['my-work', bucket, source], queryFn: () => taskApi.myWork(bucket, source),
    refetchInterval: 60_000,
  })

  const open = (item: MyWorkItem) => {
    if (item.kind === 'TASK') setParam('task', String(item.id))
    else if (item.kind === 'ACK') navigate('/shift/inbox')
    else navigate(`/handovers?id=${item.id}`)
  }

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-surface-border">
          <h1 className="text-md font-medium mr-2">내 업무</h1>
          <div className="flex gap-1" role="radiogroup" aria-label="보기">
            <button role="radio" aria-checked={view === 'list'} className={`btn btn-sm ${view === 'list' ? 'btn-primary' : ''}`}
                    onClick={() => setParam('view', null)}>목록</button>
            <button role="radio" aria-checked={view === 'board'} className={`btn btn-sm ${view === 'board' ? 'btn-primary' : ''}`}
                    onClick={() => setParam('view', 'board')}>보드</button>
            <button className="btn btn-sm" disabled title="일정·달력은 Phase 7 에서 추가됩니다">
              <CalendarDays size={12} /> 달력
            </button>
          </div>
          <span className="flex-1" />
          <button className="btn btn-sm btn-primary" onClick={() => setCreating(true)}><Plus size={12} /> 할일</button>
        </div>

        {view === 'board' ? (
          <TaskBoard assignee="me" onOpen={(id) => setParam('task', String(id))} />
        ) : (
          <div className="flex-1 min-h-0 flex flex-col p-3 gap-2">
            <div className="grid grid-cols-4 sm:grid-cols-8 gap-1.5" role="tablist" aria-label="버킷">
              {BUCKETS.map((b) => {
                const n = data?.counts[b.key] ?? 0
                const active = bucket === b.key
                return (
                  <button key={b.key} role="tab" aria-selected={active}
                          onClick={() => setParam('bucket', b.key === 'all' ? null : b.key)}
                          className={`card px-2 py-1.5 text-left ${active ? 'border-brand ring-1 ring-brand' : 'hover:border-brand/50'}`}>
                    <div className="text-xs text-ink-faint">{b.label}</div>
                    <div className={`text-lg font-semibold tabular-nums ${n ? (b.tone ?? 'text-ink') : 'text-ink-faint'}`}>{n}</div>
                  </button>
                )
              })}
            </div>

            <div className="flex flex-wrap items-center gap-1">
              {SOURCES.map((s) => (
                <button key={s.key} className={`btn btn-sm ${source === s.key ? 'btn-primary' : ''}`}
                        onClick={() => setParam('source', s.key === 'all' ? null : s.key)}>{s.label}</button>
              ))}
              <span className="flex-1" />
              {data && <span className="text-sm text-ink-faint">오늘 {data.today} · 이번 주는 {data.week_end} 까지</span>}
            </div>

            <div className="flex-1 min-h-0 overflow-auto border border-surface-border rounded bg-surface">
              <table className="w-full text-base whitespace-nowrap">
                <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
                  <tr>
                    <th className="text-left font-medium px-2 py-1">구분</th>
                    <th className="text-left font-medium px-2 py-1">제목</th>
                    <th className="text-left font-medium px-2 py-1">관계사</th>
                    <th className="text-left font-medium px-2 py-1">마감·수행일</th>
                    <th className="text-left font-medium px-2 py-1">상태</th>
                    <th className="text-left font-medium px-2 py-1">출처</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.items ?? []).length === 0 && (
                    <tr><td colSpan={6} className="py-6 text-center text-ink-faint">{isFetching ? '불러오는 중…' : '해당하는 업무가 없습니다.'}</td></tr>
                  )}
                  {(data?.items ?? []).map((item) => {
                    const kind = KIND[item.kind]
                    const Icon = kind.icon
                    return (
                      <tr key={`${item.kind}-${item.id}`} onClick={() => open(item)}
                          className={`border-t border-surface-border/60 cursor-pointer hover:bg-surface-sunken ${item.kind === 'TASK' && openId === item.id ? 'bg-brand-soft' : ''}`}>
                        <td className={`px-2 py-1 ${kind.tone}`}><span className="inline-flex items-center gap-1"><Icon size={12} />{kind.label}</span></td>
                        <td className="px-2 py-1 max-w-[420px] truncate">
                          {item.priority_code === 'URGENT' && <span className="text-state-urgent mr-1">⛔</span>}
                          {item.priority_code === 'HIGH' && <span className="text-state-high mr-1">▲</span>}
                          {item.title}
                          {item.checklist_total ? <span className="ml-1 text-xs text-ink-faint tabular-nums">{item.checklist_done}/{item.checklist_total}</span> : null}
                        </td>
                        <td className="px-2 py-1">{item.company ?? '-'}</td>
                        <td className={`px-2 py-1 tabular-nums ${item.is_overdue ? 'text-state-urgent font-medium' : ''}`}>
                          {item.due ?? '-'}{item.is_overdue && ' 지연'}
                        </td>
                        <td className="px-2 py-1">
                          {item.kind === 'ACK'
                            ? <span className="text-state-check">{item.ack_state === 'REACK_REQUIRED' ? '재확인' : '확인 대기'}</span>
                            : item.kind === 'TASK' ? STATUS_LABEL[item.status_code as TaskStatus] ?? item.status : item.status}
                        </td>
                        <td className="px-2 py-1 text-ink-muted">
                          {item.kind === 'ACK' ? `${item.from_user ?? '-'} 인계` : item.kind === 'TASK'
                            ? (item.handover_id ? `인수인계 #${item.handover_id}` : '직접') : '담당'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {openId != null && <TaskDrawer taskId={openId} onClose={() => setParam('task', null)} />}
      {creating && <TaskCreateDialog onClose={() => setCreating(false)} onCreated={(t) => setParam('task', String(t.id))} />}
    </div>
  )
}
