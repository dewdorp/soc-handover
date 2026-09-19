/**
 * 할일 보드 (FR-D-03·05) — 할일 · 진행중 · 대기 · 완료(최근 14일).
 *
 * 카드를 끌어 다른 칸에 놓으면 상태가 바뀌고(감사 기록), 같은 칸 안에서는 순서만 바뀐다.
 * 위치는 '바로 앞 카드'로 서버에 보낸다 — 담당자로 걸러진 보드에서도 전체 순서가 맞다.
 * 놓는 즉시 화면에서 옮겨 보여주고, 서버가 거절하면(409·권한) 되돌린 뒤 이유를 알린다.
 * 고칠 수 없는 카드(남의 할일)는 끌 수 없다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, MessageSquare, X } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import {
  BOARD_COLUMNS, STATUS_LABEL, TASK_QUERY_KEYS, taskApi,
  type Assignee, type Board, type BoardStatus, type Task,
} from '@/services/api/tasks'

interface Drop { status: BoardStatus; beforeId: number | null }

export default function TaskBoard({ assignee, onOpen }: { assignee: Assignee; onOpen: (id: number) => void }) {
  const qc = useQueryClient()
  const key = ['task-board', assignee]
  const { data, isLoading } = useQuery({ queryKey: key, queryFn: () => taskApi.board(assignee) })
  const [dragging, setDragging] = useState<Task | null>(null)
  const [over, setOver] = useState<Drop | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const move = useMutation({
    mutationFn: ({ task, status, afterId }: { task: Task; status: BoardStatus; afterId: number | null }) =>
      taskApi.move(task.id, task.version_no, status, afterId),
    onMutate: async ({ task, status, afterId }) => {
      await qc.cancelQueries({ queryKey: key })
      const before = qc.getQueryData<Board>(key)
      if (before) qc.setQueryData<Board>(key, place(before, task, status, afterId))
      return { before }
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.before) qc.setQueryData(key, ctx.before)
      setNotice(err instanceof ApiRequestError && err.status === 409
        ? '다른 사람이 먼저 이 카드를 바꿨습니다. 최신 보드로 다시 불러왔습니다.'
        : err instanceof ApiRequestError ? err.message : '옮기지 못했습니다.')
    },
    onSuccess: () => setNotice(null),
    onSettled: () => { for (const k of TASK_QUERY_KEYS) qc.invalidateQueries({ queryKey: [k] }) },
  })

  const drop = (target: Drop) => {
    const task = dragging
    setDragging(null); setOver(null)
    if (!task || !data) return
    const others = data.columns[target.status].filter((t) => t.id !== task.id)
    let afterId: number | null
    if (target.status === 'DONE') afterId = null          // 완료 칸은 완료 시각순
    else if (target.beforeId == null) afterId = others.at(-1)?.id ?? null
    else {
      const at = others.findIndex((t) => t.id === target.beforeId)
      afterId = at > 0 ? others[at - 1].id : null
    }
    const column = data.columns[task.status as BoardStatus] ?? []
    const index = column.findIndex((t) => t.id === task.id)
    const unchanged = target.status === task.status &&
      (index > 0 ? column[index - 1].id : null) === afterId
    if (!unchanged) move.mutate({ task, status: target.status, afterId })
  }

  if (isLoading || !data) return <p className="p-3 text-ink-faint">불러오는 중…</p>

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {notice && (
        <p role="alert" className="mx-3 mt-2 text-sm text-state-check bg-amber-50 border border-amber-200 rounded px-2 py-1 flex items-center gap-2">
          <span className="flex-1">{notice}</span>
          <button onClick={() => setNotice(null)} aria-label="안내 닫기" className="hover:text-ink"><X size={12} /></button>
        </p>
      )}
      <div className="flex-1 min-h-0 grid grid-cols-[repeat(4,minmax(15rem,1fr))] gap-2 p-3 overflow-x-auto">
        {BOARD_COLUMNS.map((status) => {
          const cards = data.columns[status]
          const isOver = over?.status === status
          return (
            <section key={status} aria-label={`${STATUS_LABEL[status]} 칸`}
                     className={`flex flex-col min-h-0 rounded-md border bg-surface-sunken ${isOver ? 'border-brand ring-1 ring-brand' : 'border-surface-border'}`}
                     onDragOver={(e) => { if (dragging) { e.preventDefault(); if (!isOver || over?.beforeId != null) setOver({ status, beforeId: null }) } }}
                     onDrop={(e) => { e.preventDefault(); drop({ status, beforeId: null }) }}>
              <header className="px-2 py-1.5 flex items-center gap-2 border-b border-surface-border">
                <h3 className="font-medium">{STATUS_LABEL[status]}</h3>
                <span className="chip h-5 tabular-nums">{data.counts[status]}</span>
                {status === 'DONE' && <span className="text-xs text-ink-faint">최근 14일</span>}
              </header>
              <ul className="flex-1 min-h-[6rem] overflow-y-auto p-1.5 space-y-1.5">
                {cards.map((t) => (
                  <li key={t.id}
                      onDragOver={(e) => { if (dragging && dragging.id !== t.id) { e.preventDefault(); e.stopPropagation(); if (over?.beforeId !== t.id) setOver({ status, beforeId: t.id }) } }}
                      onDrop={(e) => { e.preventDefault(); e.stopPropagation(); drop({ status, beforeId: t.id }) }}>
                    {isOver && over?.beforeId === t.id && <div className="h-1 rounded bg-brand mb-1" aria-hidden />}
                    <Card task={t} dragging={dragging?.id === t.id} onOpen={() => onOpen(t.id)}
                          onDragStart={() => setDragging(t)} onDragEnd={() => { setDragging(null); setOver(null) }}
                          showAssignee={assignee !== 'me'} />
                  </li>
                ))}
                {isOver && over?.beforeId == null && dragging && <li className="h-1 rounded bg-brand" aria-hidden />}
                {cards.length === 0 && !isOver && <li className="text-center text-ink-faint text-sm py-4">비어 있음</li>}
              </ul>
            </section>
          )
        })}
      </div>
    </div>
  )
}

/** 서버 응답 전에 화면에서 먼저 옮긴다(실패하면 되돌린다). */
function place(board: Board, task: Task, status: BoardStatus, afterId: number | null): Board {
  const columns = Object.fromEntries(
    Object.entries(board.columns).map(([k, list]) => [k, list.filter((t) => t.id !== task.id)]),
  ) as Board['columns']
  const moved = { ...task, status }
  const list = columns[status]
  const at = afterId == null ? 0 : list.findIndex((t) => t.id === afterId) + 1
  list.splice(status === 'DONE' ? 0 : Math.max(0, at), 0, moved)
  const counts = Object.fromEntries(Object.entries(columns).map(([k, v]) => [k, v.length])) as Board['counts']
  return { ...board, columns, counts }
}

function Card({ task, dragging, showAssignee, onOpen, onDragStart, onDragEnd }: {
  task: Task; dragging: boolean; showAssignee: boolean
  onOpen: () => void; onDragStart: () => void; onDragEnd: () => void
}) {
  return (
    <div draggable={task.can_edit}
         onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(task.id)); onDragStart() }}
         onDragEnd={onDragEnd}
         role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => { if (e.key === 'Enter') onOpen() }}
         title={task.can_edit ? '끌어서 옮기기 · 눌러서 열기' : '남의 할일은 옮길 수 없습니다(눌러서 열기)'}
         className={`card px-2 py-1.5 space-y-1 bg-surface hover:border-brand/50 ${task.can_edit ? 'cursor-grab' : 'cursor-pointer'} ${dragging ? 'opacity-40' : ''}`}>
      <div className="flex items-start gap-1">
        {task.priority?.code === 'URGENT' && <span className="text-state-urgent" title="긴급">⛔</span>}
        {task.priority?.code === 'HIGH' && <span className="text-state-high" title="높음">▲</span>}
        <span className="break-words min-w-0">{task.title}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-muted">
        {task.company && <span>{task.company.short_name ?? task.company.name}</span>}
        {task.due_date && (
          <span className={task.is_overdue ? 'text-state-urgent font-medium' : ''}>
            {task.is_overdue ? '지연 · ' : ''}{task.due_date.slice(5).replace('-', '/')}
          </span>
        )}
        {showAssignee && <span>{task.assignee?.display_name ?? '(미지정)'}</span>}
        {task.checklist_total > 0 && (
          <span className={`inline-flex items-center gap-0.5 ${task.checklist_done === task.checklist_total ? 'text-state-done' : ''}`}>
            <CheckSquare size={10} />{task.checklist_done}/{task.checklist_total}
          </span>
        )}
        {task.comment_count > 0 && <span className="inline-flex items-center gap-0.5"><MessageSquare size={10} />{task.comment_count}</span>}
        {task.handover && <span className="text-brand">#{task.handover.id}</span>}
      </div>
    </div>
  )
}
