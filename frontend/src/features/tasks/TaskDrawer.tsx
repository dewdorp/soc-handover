/**
 * 할일 상세 (UI_STRUCTURE §6) — 필드 · 체크리스트 · 연결 일정 · 첨부 · 댓글.
 *
 * 선택 칸(상태·중요도·담당자·날짜)은 고르는 즉시 저장한다. 제목·내용은 '편집'으로.
 * 모든 저장에 지금 보고 있는 버전(expected_version)을 함께 보낸다 — 그사이 다른 사람이
 * 고쳤으면 409 를 받고, 무엇이 저장되지 않았는지 알린 뒤 최신 값을 다시 불러온다.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Trash2, X } from 'lucide-react'
import Attachments from '@/components/Attachments'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import LinkedSchedules from '@/features/calendar/LinkedSchedules'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import {
  STATUS_LABEL, TASK_QUERY_KEYS, taskApi, type TaskChanges, type TaskDetail, type TaskStatus,
} from '@/services/api/tasks'

const FIELD_LABEL: Record<string, string> = {
  title: '제목', description: '내용', status: '상태', priority_code: '중요도', assignee_id: '담당자',
  company_id: '관계사', start_date: '시작일', due_date: '마감일',
}

function when(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export default function TaskDrawer({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [notice, setNotice] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ title: '', description: '' })
  const [confirmDelete, setConfirmDelete] = useState(false)

  const { data: task, isLoading, error: loadError } = useQuery({
    queryKey: ['task', taskId], queryFn: () => taskApi.get(taskId),
  })
  const { data: users } = useQuery({ queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000 })
  const { data: priorities } = useQuery({ queryKey: ['priorities'], queryFn: referenceApi.priorities, staleTime: 300_000 })
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 60_000 })

  useEffect(() => { setEditing(false); setNotice(null) }, [taskId])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !confirmDelete) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, confirmDelete])

  const refresh = () => { for (const key of TASK_QUERY_KEYS) qc.invalidateQueries({ queryKey: [key] }) }
  const fail = (err: unknown, what: string) => {
    if (err instanceof ApiRequestError && err.status === 409) {
      setNotice(`다른 사람이 먼저 고쳐서 '${what}' 변경은 저장되지 않았습니다. 최신 내용으로 다시 불러왔습니다.`)
      refresh()
    } else {
      setNotice(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')
    }
  }

  const save = useMutation({
    mutationFn: (changes: TaskChanges) => taskApi.update(taskId, task!.version_no, changes),
    onSuccess: (fresh) => {
      qc.setQueryData(['task', taskId], fresh)
      setNotice(null); setEditing(false)
      refresh()
    },
    onError: (err, changes) => fail(err, Object.keys(changes).map((k) => FIELD_LABEL[k] ?? k).join(', ')),
  })
  const remove = useMutation({
    mutationFn: (reason: string) => taskApi.remove(taskId, reason || undefined),
    onSuccess: () => { refresh(); onClose() },
    onError: (err) => fail(err, '삭제'),
  })

  const shell = 'w-full lg:w-[480px] max-lg:fixed max-lg:inset-x-0 max-lg:top-12 max-lg:bottom-0 max-lg:z-30 max-lg:shadow-xl ' +
    'shrink-0 border-l border-surface-border bg-surface flex flex-col min-h-0'

  if (isLoading || !task) {
    return (
      <aside className={`${shell} grid place-items-center text-ink-faint`} aria-label="할일 상세">
        {loadError ? '할일을 찾을 수 없습니다(삭제되었을 수 있습니다).' : '불러오는 중…'}
        {loadError && <button className="btn btn-sm mt-2" onClick={onClose}>닫기</button>}
      </aside>
    )
  }

  const canEdit = task.can_edit
  const canDelete = !!me && (me.id === task.creator?.id || me.permissions.includes('task:delete_any'))
  const patch = (changes: TaskChanges) => save.mutate(changes)

  return (
    <aside className={shell} aria-label="할일 상세">
      <div className="px-3 py-2 border-b border-surface-border space-y-1">
        <div className="flex items-center gap-2">
          <span className="font-medium tabular-nums">할일 #{task.id}</span>
          {task.is_overdue && <span className="chip h-5 text-state-urgent border-red-200 bg-red-50">지연</span>}
          <span className="flex-1" />
          <span className="text-ink-faint tabular-nums text-sm">v{task.version_no}</span>
          {canEdit && !editing && (
            <button className="btn btn-sm" onClick={() => { setDraft({ title: task.title, description: task.description ?? '' }); setEditing(true) }}>
              편집
            </button>
          )}
          {canDelete && (
            <button className="btn btn-sm text-state-urgent" onClick={() => setConfirmDelete(true)} aria-label="삭제">
              <Trash2 size={12} />
            </button>
          )}
          <button className="text-ink-faint hover:text-ink" onClick={onClose} aria-label="닫기"><X size={16} /></button>
        </div>
        {editing ? (
          <input className="input w-full text-md font-medium" value={draft.title}
                 onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} aria-label="제목" />
        ) : (
          <h2 className="text-md font-medium break-words">{task.title}</h2>
        )}
        {!canEdit && <p className="text-xs text-ink-faint">만든 사람·담당자만 고칠 수 있습니다(관리자 제외).</p>}
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-4">
        {notice && <p role="alert" className="text-sm text-state-check bg-amber-50 border border-amber-200 rounded px-2 py-1">{notice}</p>}

        <dl className="grid grid-cols-[5rem_1fr] gap-x-2 gap-y-1.5 items-center">
          <dt className="text-ink-muted">상태</dt>
          <dd>
            <select className="input h-7" value={task.status} disabled={!canEdit || save.isPending}
                    onChange={(e) => patch({ status: e.target.value as TaskStatus })} aria-label="상태">
              {(Object.keys(STATUS_LABEL) as TaskStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
            {task.completed_at && <span className="ml-2 text-sm text-state-done">완료 {when(task.completed_at)}</span>}
          </dd>
          <dt className="text-ink-muted">중요도</dt>
          <dd>
            <select className="input h-7" value={task.priority?.code ?? 'NORMAL'} disabled={!canEdit || save.isPending}
                    onChange={(e) => patch({ priority_code: e.target.value })} aria-label="중요도">
              {(priorities ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </select>
          </dd>
          <dt className="text-ink-muted">담당자</dt>
          <dd>
            <select className="input h-7" value={task.assignee?.id ?? ''} disabled={!canEdit || save.isPending}
                    onChange={(e) => patch({ assignee_id: e.target.value ? Number(e.target.value) : null })} aria-label="담당자">
              <option value="">(미지정)</option>
              {(users ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
            </select>
          </dd>
          <dt className="text-ink-muted">마감일</dt>
          <dd className="flex items-center gap-2">
            <input type="date" className={`input h-7 ${task.is_overdue ? 'text-state-urgent' : ''}`} value={task.due_date ?? ''}
                   disabled={!canEdit || save.isPending} onChange={(e) => patch({ due_date: e.target.value || null })} aria-label="마감일" />
          </dd>
          <dt className="text-ink-muted">시작일</dt>
          <dd>
            <input type="date" className="input h-7" value={task.start_date ?? ''} disabled={!canEdit || save.isPending}
                   onChange={(e) => patch({ start_date: e.target.value || null })} aria-label="시작일" />
          </dd>
          <dt className="text-ink-muted">관계사</dt>
          <dd>
            <select className="input h-7" value={task.company?.id ?? ''} disabled={!canEdit || save.isPending}
                    onChange={(e) => patch({ company_id: e.target.value ? Number(e.target.value) : null })} aria-label="관계사">
              <option value="">(없음)</option>
              {(companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </dd>
          <dt className="text-ink-muted">인수인계</dt>
          <dd className="min-w-0 truncate">
            {task.handover ? (
              <Link to={`/handovers?id=${task.handover.id}`} className="text-brand hover:underline">
                #{task.handover.id} {task.handover.title}{task.handover.is_deleted && ' (삭제됨)'}
              </Link>
            ) : <span className="text-ink-faint">-</span>}
          </dd>
          <dt className="text-ink-muted">만든 사람</dt>
          <dd className="text-ink-muted">{task.creator?.display_name ?? '-'} · {when(task.created_at)}</dd>
        </dl>

        <section className="space-y-1">
          <h3 className="text-ink-muted text-sm">내용</h3>
          {editing ? (
            <textarea className="input w-full h-32 py-1 resize-y" value={draft.description}
                      onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} aria-label="내용" />
          ) : (
            <p className="whitespace-pre-wrap break-words">{task.description || <span className="text-ink-faint">(없음)</span>}</p>
          )}
          {editing && (
            <div className="flex justify-end gap-2">
              <button className="btn btn-sm" onClick={() => setEditing(false)}>취소</button>
              <button className="btn btn-sm btn-primary" disabled={save.isPending || !draft.title.trim()}
                      onClick={() => {
                        const changes: TaskChanges = {}
                        if (draft.title.trim() !== task.title) changes.title = draft.title.trim()
                        if ((draft.description || null) !== (task.description || null)) changes.description = draft.description || null
                        if (Object.keys(changes).length) save.mutate(changes)
                        else setEditing(false)
                      }}>저장</button>
            </div>
          )}
        </section>

        <Checklist task={task} canEdit={canEdit} onChanged={refresh} />
        <LinkedSchedules task={{ id: task.id, title: task.title }} canCreate={!!me?.permissions.includes('schedule:create')} />
        <section className="space-y-1.5">
          <h3 className="text-ink-muted text-sm">첨부</h3>
          <Attachments entityType="TASK" entityId={task.id} canUpload={canEdit} />
        </section>
        <Comments taskId={task.id} onChanged={refresh} />
      </div>

      {confirmDelete && (
        <ConfirmDialog title={`할일 #${task.id} 을(를) 삭제합니다`} confirmLabel="삭제" danger busy={remove.isPending}
                       input={{ label: '사유', placeholder: '예: 중복 등록' }}
                       onCancel={() => setConfirmDelete(false)}
                       onConfirm={(reason) => { setConfirmDelete(false); remove.mutate(reason) }}>
          <p>목록과 보드에서 사라지고, 기록(감사 로그)은 남습니다.</p>
        </ConfirmDialog>
      )}
    </aside>
  )
}

function Checklist({ task, canEdit, onChanged }: { task: TaskDetail; canEdit: boolean; onChanged: () => void }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const done = task.checklists.filter((c) => c.is_done).length
  const total = task.checklists.length
  const after = () => { qc.invalidateQueries({ queryKey: ['task', task.id] }); onChanged() }

  const add = useMutation({ mutationFn: () => taskApi.addChecklist(task.id, title.trim()), onSuccess: () => { setTitle(''); after() } })
  const toggle = useMutation({ mutationFn: ({ id, is_done }: { id: number; is_done: boolean }) => taskApi.updateChecklist(id, { is_done }), onSuccess: after })
  const remove = useMutation({ mutationFn: (id: number) => taskApi.removeChecklist(id), onSuccess: after })

  return (
    <section className="space-y-1.5">
      <div className="flex items-center gap-2">
        <h3 className="text-ink-muted text-sm">체크리스트</h3>
        {total > 0 && <span className="text-sm tabular-nums text-ink-muted">{done}/{total}</span>}
      </div>
      {total > 0 && (
        <div className="h-1.5 rounded bg-surface-sunken overflow-hidden" role="progressbar"
             aria-valuenow={done} aria-valuemin={0} aria-valuemax={total} aria-label="체크리스트 진행률">
          <div className="h-full bg-state-done transition-all" style={{ width: `${(done / total) * 100}%` }} />
        </div>
      )}
      <ul className="space-y-0.5">
        {task.checklists.map((c) => (
          <li key={c.id} className="flex items-center gap-2 group">
            <input type="checkbox" checked={c.is_done} disabled={!canEdit || toggle.isPending}
                   onChange={(e) => toggle.mutate({ id: c.id, is_done: e.target.checked })} aria-label={c.title} />
            <span className={`flex-1 break-words ${c.is_done ? 'line-through text-ink-faint' : ''}`}>{c.title}</span>
            {canEdit && (
              <button className="text-ink-faint hover:text-state-urgent opacity-0 group-hover:opacity-100 focus:opacity-100"
                      onClick={() => remove.mutate(c.id)} aria-label={`${c.title} 빼기`}><X size={12} /></button>
            )}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate() }}>
          <input className="input flex-1 h-7" value={title} placeholder="항목 추가" onChange={(e) => setTitle(e.target.value)} aria-label="체크리스트 항목 추가" />
          <button className="btn btn-sm" disabled={!title.trim() || add.isPending}>추가</button>
        </form>
      )}
    </section>
  )
}

function Comments({ taskId, onChanged }: { taskId: number; onChanged: () => void }) {
  const qc = useQueryClient()
  const [body, setBody] = useState('')
  const { data } = useQuery({ queryKey: ['task-comments', taskId], queryFn: () => taskApi.comments(taskId) })
  const after = () => { qc.invalidateQueries({ queryKey: ['task-comments', taskId] }); onChanged() }
  const add = useMutation({ mutationFn: () => taskApi.addComment(taskId, body.trim()), onSuccess: () => { setBody(''); after() } })
  const remove = useMutation({ mutationFn: (id: number) => taskApi.removeComment(id), onSuccess: after })

  return (
    <section className="space-y-1.5">
      <h3 className="text-ink-muted text-sm">댓글 {data?.length ? <span className="tabular-nums">{data.length}</span> : null}</h3>
      <ul className="space-y-1.5">
        {(data ?? []).map((c) => (
          <li key={c.id} className="border border-surface-border rounded px-2 py-1">
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <span className="font-medium text-ink">{c.author ?? '-'}</span>
              <span className="tabular-nums">{when(c.created_at)}</span>
              <span className="flex-1" />
              {c.can_delete && <button className="hover:text-state-urgent" onClick={() => remove.mutate(c.id)} aria-label="댓글 지우기"><X size={12} /></button>}
            </div>
            <p className="whitespace-pre-wrap break-words">{c.body}</p>
          </li>
        ))}
      </ul>
      <form className="space-y-1" onSubmit={(e) => { e.preventDefault(); if (body.trim()) add.mutate() }}>
        <textarea className="input w-full h-14 py-1 resize-y" value={body} placeholder="댓글 (담당자·만든 사람에게 알림)"
                  onChange={(e) => setBody(e.target.value)} aria-label="댓글" />
        <div className="flex justify-end">
          <button className="btn btn-sm" disabled={!body.trim() || add.isPending}>댓글 달기</button>
        </div>
      </form>
    </section>
  )
}
