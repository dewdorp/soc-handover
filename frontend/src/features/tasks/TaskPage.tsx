/**
 * 할일 (UI_STRUCTURE §6) — 목록(/tasks) · 보드(/tasks/board).
 *
 * 담당 필터와 열린 할일은 주소에 둔다(?assignee=me&id=12) — 알림·인수인계에서 바로 열린다.
 */
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { NavLink, useLocation, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import TaskBoard from '@/features/tasks/TaskBoard'
import TaskCreateDialog from '@/features/tasks/TaskCreateDialog'
import TaskDrawer from '@/features/tasks/TaskDrawer'
import { useCan } from '@/hooks/useAuth'
import { STATUS_LABEL, STATUS_TONE, taskApi, type Assignee, type TaskSearch } from '@/services/api/tasks'

const ASSIGNEE_TABS: { key: Assignee; label: string }[] = [
  { key: 'all', label: '전체' }, { key: 'me', label: '내 할일' }, { key: 'unassigned', label: '미지정' },
]
const PAGE = 100

export default function TaskPage() {
  const { pathname } = useLocation()
  const [params, setParams] = useSearchParams()
  const can = useCan()
  const board = pathname.startsWith('/tasks/board')
  const assignee = (params.get('assignee') as Assignee | null) ?? 'all'
  const openId = params.get('id') ? Number(params.get('id')) : null
  const [creating, setCreating] = useState(false)

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: key !== 'id' })
  }
  const tab = (active: boolean) =>
    `px-3 h-8 inline-flex items-center border-b-2 ${active ? 'border-brand text-brand font-medium' : 'border-transparent text-ink-muted hover:text-ink'}`
  const query = params.toString() ? `?${new URLSearchParams([...params].filter(([k]) => k !== 'id'))}` : ''

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <nav className="flex flex-wrap items-center gap-1 px-3 border-b border-surface-border" aria-label="할일">
          <h1 className="text-md font-medium mr-3">할일</h1>
          <NavLink to={`/tasks${query}`} end className={() => tab(!board)}>목록</NavLink>
          <NavLink to={`/tasks/board${query}`} className={() => tab(board)}>보드</NavLink>
          <span className="flex-1" />
          <div className="flex gap-1 py-1" role="radiogroup" aria-label="담당">
            {ASSIGNEE_TABS.map((a) => (
              <button key={String(a.key)} role="radio" aria-checked={assignee === a.key}
                      className={`btn btn-sm ${assignee === a.key ? 'btn-primary' : ''}`}
                      onClick={() => setParam('assignee', a.key === 'all' ? null : String(a.key))}>{a.label}</button>
            ))}
          </div>
          {can('task:create') && (
            <button className="btn btn-sm btn-primary ml-2" onClick={() => setCreating(true)}><Plus size={12} /> 할일</button>
          )}
        </nav>

        {board
          ? <TaskBoard assignee={assignee} onOpen={(id) => setParam('id', String(id))} />
          : <TaskList key={`${params.get('q') ?? ''}|${params.get('closed') ?? ''}`} assignee={assignee} openId={openId}
                      initialQ={params.get('q') ?? ''} initialClosed={params.get('closed') === '1'}
                      onOpen={(id) => setParam('id', String(id))} />}
      </div>

      {openId != null && <TaskDrawer taskId={openId} onClose={() => setParam('id', null)} />}
      {creating && <TaskCreateDialog onClose={() => setCreating(false)} onCreated={(t) => setParam('id', String(t.id))} />}
    </div>
  )
}

function TaskList({ assignee, openId, onOpen, initialQ, initialClosed }: {
  assignee: Assignee; openId: number | null; onOpen: (id: number) => void
  initialQ: string; initialClosed: boolean                 // 통합검색 '목록에서 모두 보기'로 넘어온 값
}) {
  const [q, setQ] = useState(initialQ)
  const [includeClosed, setIncludeClosed] = useState(initialClosed)
  const [due, setDue] = useState<TaskSearch['due']>(null)
  const [page, setPage] = useState(1)
  const body: TaskSearch = { q: q.trim() || undefined, assignee, include_closed: includeClosed, due, page, size: PAGE }
  const { data, isFetching } = useQuery({
    queryKey: ['tasks', body], queryFn: () => taskApi.search(body), placeholderData: keepPreviousData,
  })
  const rows = data?.items ?? []
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1

  return (
    <div className="flex-1 min-h-0 flex flex-col p-3 gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input w-56" placeholder="제목·내용 검색" value={q} aria-label="할일 검색"
               onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <select className="input" value={due ?? ''} aria-label="마감"
                onChange={(e) => { setDue((e.target.value || null) as TaskSearch['due']); setPage(1) }}>
          <option value="">마감 전체</option>
          <option value="overdue">지연</option>
          <option value="today">오늘</option>
          <option value="this_week">이번 주</option>
          <option value="none">마감 없음</option>
        </select>
        <label className="inline-flex items-center gap-1 text-ink-muted">
          <input type="checkbox" checked={includeClosed} onChange={(e) => { setIncludeClosed(e.target.checked); setPage(1) }} />
          완료·취소 포함
        </label>
        <span className="flex-1" />
        <span className="text-sm text-ink-faint tabular-nums">{isFetching ? '불러오는 중…' : `${data?.total ?? 0}건`}</span>
      </div>

      <div className="flex-1 min-h-0 overflow-auto border border-surface-border rounded bg-surface">
        <table className="w-full text-base whitespace-nowrap">
          <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
            <tr>
              <th className="text-left font-medium px-2 py-1">상태</th>
              <th className="text-left font-medium px-2 py-1">제목</th>
              <th className="text-left font-medium px-2 py-1">관계사</th>
              <th className="text-left font-medium px-2 py-1">담당</th>
              <th className="text-left font-medium px-2 py-1">마감</th>
              <th className="text-left font-medium px-2 py-1">체크</th>
              <th className="text-left font-medium px-2 py-1">인수인계</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-ink-faint">{isFetching ? '' : '할일이 없습니다.'}</td></tr>
            )}
            {rows.map((t) => (
              <tr key={t.id} onClick={() => onOpen(t.id)}
                  className={`border-t border-surface-border/60 cursor-pointer hover:bg-surface-sunken ${openId === t.id ? 'bg-brand-soft' : ''}`}>
                <td className={`px-2 py-1 ${STATUS_TONE[t.status]}`}>{STATUS_LABEL[t.status]}</td>
                <td className="px-2 py-1 max-w-[420px]">
                  <button className="truncate max-w-full text-left hover:underline" onClick={(e) => { e.stopPropagation(); onOpen(t.id) }}>
                    {t.priority?.code === 'URGENT' && <span className="text-state-urgent mr-1">⛔</span>}
                    {t.priority?.code === 'HIGH' && <span className="text-state-high mr-1">▲</span>}
                    {t.title}
                  </button>
                </td>
                <td className="px-2 py-1">{t.company?.short_name ?? t.company?.name ?? '-'}</td>
                <td className="px-2 py-1">{t.assignee?.display_name ?? <span className="text-ink-faint">(미지정)</span>}</td>
                <td className={`px-2 py-1 tabular-nums ${t.is_overdue ? 'text-state-urgent font-medium' : ''}`}>
                  {t.due_date ?? '-'}{t.is_overdue && ' 지연'}
                </td>
                <td className="px-2 py-1 tabular-nums">{t.checklist_total ? `${t.checklist_done}/${t.checklist_total}` : '-'}</td>
                <td className="px-2 py-1 tabular-nums">{t.handover ? <span className="text-brand">#{t.handover.id}</span> : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</button>
          <span className="tabular-nums text-sm">{page} / {pages}</span>
          <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>다음</button>
        </div>
      )}
    </div>
  )
}
