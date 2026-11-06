/**
 * 인수인계 상세 Drawer (UI_STRUCTURE §4).
 *
 * 목록 컨텍스트를 유지한 채 우측에서 열린다. 수정은 인라인 편집 + 변경 사유이고,
 * 저장은 expected_version 을 함께 보낸다 → 충돌 시 409 를 받아 다이얼로그를 띄운다.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, Pin, Plus, Star, Trash2, X } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import AnalysisRequest from '@/features/handovers/AnalysisRequest'
import ParticipantsPanel from '@/features/handovers/ParticipantsPanel'
import RelatedKnowledge from '@/features/handovers/RelatedKnowledge'
import ScopePicker, { ScopeBadge, type Visibility } from '@/features/handovers/ScopePicker'
import ScopeWarning from '@/features/handovers/ScopeWarning'
import ConflictDialog from '@/features/handovers/ConflictDialog'
import TaskCreateDialog from '@/features/tasks/TaskCreateDialog'
import LinkedSchedules from '@/features/calendar/LinkedSchedules'
import HandoverComments from '@/features/handovers/HandoverComments'
import Attachments from '@/components/Attachments'
import VersionHistory, { fieldLabel } from '@/features/handovers/VersionHistory'
import { ApiRequestError } from '@/services/api/client'
import { handoverApi } from '@/services/api/handovers'
import { STATUS_LABEL, STATUS_TONE, taskApi } from '@/services/api/tasks'
import { useMe } from '@/hooks/useAuth'
import type { Company, HandoverStatus, Priority } from '@/types/api'
import type { VersionConflictDetail } from '@/types/handover'

type Tab = 'detail' | 'tasks' | 'schedules' | 'comments' | 'files' | 'versions' | 'timeline'

interface Props {
  handoverId: number
  companies: Company[]
  statuses: HandoverStatus[]
  priorities: Priority[]
  onClose: () => void
  /** 목록에서 'e' 를 누를 때마다 1씩 오른다 — 수정 모드로 연다 */
  editNonce?: number
}

export default function HandoverDrawer({ handoverId, companies, statuses, priorities, onClose, editNonce = 0 }: Props) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [tab, setTab] = useState<Tab>('detail')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [reason, setReason] = useState('')
  const [conflict, setConflict] = useState<VersionConflictDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [creatingTask, setCreatingTask] = useState(false)

  const { data: row, isLoading } = useQuery({
    queryKey: ['handover', handoverId],
    queryFn: () => handoverApi.get(handoverId),
  })

  useEffect(() => {
    setTab('detail'); setEditing(false); setDraft({}); setReason(''); setConflict(null)
    handoverApi.markViewed(handoverId).catch(() => undefined)
  }, [handoverId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !conflict && !confirmDelete && !creatingTask) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, conflict, confirmDelete, creatingTask])

  const canEdit = useMemo(() => {
    if (!row || !me) return false
    if (me.permissions.includes('handover:update_any')) return true
    return row.created_by === me.id || row.assignee?.id === me.id
  }, [row, me])

  // 'e' 단축키: 이 건이 불러와진 뒤에 한 번만 처리한다(목록에서 행을 바꾸며 누르면 새 건이 올 때까지 기다린다)
  const handledEdit = useRef(0)
  useEffect(() => {
    if (!editNonce || editNonce === handledEdit.current || !row || row.id !== handoverId || !me) return
    handledEdit.current = editNonce
    if (canEdit && !row.is_deleted) { setTab('detail'); setEditing(true) }
    else setError('이 인수인계는 수정할 수 없습니다. 작성자 · 담당자 · 관리자만 고칠 수 있습니다.')
  }, [editNonce, row, me, canEdit, handoverId])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['handover', handoverId] })
    qc.invalidateQueries({ queryKey: ['handovers'] })
    qc.invalidateQueries({ queryKey: ['facet'] })
  }

  const save = useMutation({
    mutationFn: () => handoverApi.update(handoverId, {
      ...draft, expected_version: row!.current_version_no,
      change_reason: reason.trim() || null,
    }),
    onSuccess: () => {
      setEditing(false); setDraft({}); setReason(''); setError(null)
      invalidate()
      qc.invalidateQueries({ queryKey: ['versions', handoverId] })
    },
    onError: (err) => {
      if (err instanceof ApiRequestError && err.status === 409) {
        setConflict(err.detail as unknown as VersionConflictDetail)
      } else {
        setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')
      }
    },
  })

  const [ackHeld, setAckHeld] = useState<{ current: number; fields: string[] } | null>(null)
  const ack = useMutation({
    // 지금 화면이 보여 주고 있는 버전으로만 확인한다 — 열어 둔 사이 바뀌었으면 서버가 막는다
    mutationFn: () => handoverApi.acknowledge(handoverId, row?.current_version_no ?? null),
    onSuccess: () => {
      setAckHeld(null)
      invalidate()
      for (const key of ['inbox', 'me', 'my-work', 'cockpit', 'shift-history', 'kpi']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
    },
    onError: (err) => {
      const detail = err instanceof ApiRequestError && err.code === 'stale_ack'
        ? (err.detail as { current_version_no: number; changed_fields: string[] }) : null
      if (!detail) return
      setAckHeld({ current: detail.current_version_no, fields: detail.changed_fields })
      invalidate()   // 바뀐 내용을 바로 보여 준다
    },
  })

  const star = useMutation({
    mutationFn: (on: boolean) => handoverApi.star(handoverId, on),
    onSuccess: invalidate,
  })

  const pin = useMutation({
    mutationFn: (on: boolean) => handoverApi.pin(handoverId, on),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (why: string) => handoverApi.remove(handoverId, why),
    onSuccess: () => { invalidate(); onClose() },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '삭제하지 못했습니다.'),
  })

  if (isLoading || !row) {
    return (
      <aside className="w-full lg:w-[520px] max-lg:fixed max-lg:inset-x-0 max-lg:top-12 max-lg:bottom-0 max-lg:z-30 max-lg:shadow-xl
                      shrink-0 border-l border-surface-border bg-surface
                        grid place-items-center text-ink-faint">
        불러오는 중…
      </aside>
    )
  }

  /** 편집 중이면 draft 값을, 아니면 서버 값을 쓴다. */
  const field = (key: string, fallback: unknown) => (key in draft ? draft[key] : fallback)
  const set = (key: string, value: unknown) => setDraft((d) => ({ ...d, [key]: value }))

  const myAck = row.acknowledgements.find((a) => a.user_id === me?.id)

  return (
    <aside className="w-full lg:w-[520px] max-lg:fixed max-lg:inset-x-0 max-lg:top-12 max-lg:bottom-0 max-lg:z-30 max-lg:shadow-xl
                      shrink-0 border-l border-surface-border bg-surface
                      flex flex-col min-h-0" aria-label="인수인계 상세">
      {/* 헤더 */}
      <div className="px-3 py-2 border-b border-surface-border space-y-1">
        <div className="flex items-center gap-2">
          <span className="font-medium tabular-nums">#{row.id}</span>
          <button onClick={() => star.mutate(!row.is_starred)}
                  className={row.is_starred ? 'text-amber-500' : 'text-ink-faint hover:text-amber-500'}
                  aria-label="즐겨찾기">
            <Star size={14} fill={row.is_starred ? 'currentColor' : 'none'} />
          </button>
          {me?.permissions.includes('handover:pin') && (
            <button onClick={() => pin.mutate(!row.is_pinned)}
                    className={row.is_pinned ? 'text-brand' : 'text-ink-faint hover:text-brand'}
                    aria-label="상단고정">
              <Pin size={14} fill={row.is_pinned ? 'currentColor' : 'none'} />
            </button>
          )}
          <span className="flex-1" />
          {canEdit && !editing && (
            <button className="btn btn-sm" onClick={() => setEditing(true)}>수정</button>
          )}
          {me?.permissions.includes('handover:delete') && !editing && (
            <button className="btn btn-sm text-state-urgent"
                    onClick={() => setConfirmDelete(true)} aria-label="삭제"><Trash2 size={12} /></button>
          )}
          <button className="text-ink-faint hover:text-ink" onClick={onClose} aria-label="닫기">
            <X size={16} />
          </button>
        </div>
        <div className="flex items-center gap-2 text-ink-muted">
          <span>{row.priority?.name}</span>
          <span>·</span>
          <span>{row.status?.name}</span>
          <span>·</span>
          <span>{row.company?.name}</span>
          <span className="flex-1" />
          <span className="tabular-nums">v{row.current_version_no}</span>
        </div>
        {row.is_deleted && (
          <p className="text-sm text-state-urgent">
            삭제된 항목입니다. 사유: {row.delete_reason ?? '(없음)'}
          </p>
        )}
      </div>

      {/* 탭 */}
      <nav className="flex gap-1 px-3 pt-2 border-b border-surface-border overflow-x-auto whitespace-nowrap" role="tablist">
        {([['detail', '상세'], ['tasks', `할일${row.task_count ? ` ${row.task_count}` : ''}`],
           ['schedules', `일정${row.schedule_count ? ` ${row.schedule_count}` : ''}`],
           ['comments', `댓글${row.comment_count ? ` ${row.comment_count}` : ''}`],
           ['files', `첨부${row.attachment_count ? ` ${row.attachment_count}` : ''}`],
           ['versions', '변경이력'], ['timeline', '전체 이력']] as [Tab, string][])
          .map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key}
                    onClick={() => setTab(key)}
                    className={`px-2 h-7 shrink-0 rounded-t border-b-2 ${tab === key
                      ? 'border-brand text-brand font-medium' : 'border-transparent text-ink-muted'}`}>
              {label}
            </button>
          ))}
      </nav>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border
                                     border-red-200 rounded px-2 py-1">{error}</p>
        )}

        {tab === 'detail' && (
          <>
            {editing ? (
              <input className="input w-full text-md font-medium"
                     value={String(field('title', row.title) ?? '')}
                     onChange={(e) => set('title', e.target.value)} />
            ) : (
              <h2 className="text-md font-medium break-words">{row.title}</h2>
            )}

            <dl className="grid grid-cols-[72px_1fr] gap-x-2 gap-y-1 items-center">
              <Field label="관계사">
                {editing ? (
                  <select className="input w-full" value={String(field('company_id', row.company?.id ?? ''))}
                          onChange={(e) => set('company_id', Number(e.target.value))}>
                    {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                ) : row.company?.name ?? '-'}
              </Field>
              <Field label="상태">
                {editing ? (
                  <select className="input w-full" value={String(field('status_code', row.status?.code) ?? '')}
                          onChange={(e) => set('status_code', e.target.value)}>
                    {statuses.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                  </select>
                ) : row.status?.name ?? '-'}
              </Field>
              <Field label="중요도">
                {editing ? (
                  <select className="input w-full" value={String(field('priority_code', row.priority?.code) ?? '')}
                          onChange={(e) => set('priority_code', e.target.value)}>
                    {priorities.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                  </select>
                ) : row.priority?.name ?? '-'}
              </Field>
              <Field label="등록일">{row.registered_date}</Field>
              <Field label="수행일">
                {editing ? (
                  <input type="date" className="input w-full"
                         value={String(field('work_date', row.work_date) ?? '')}
                         onChange={(e) => set('work_date', e.target.value || null)} />
                ) : row.work_date ?? '-'}
              </Field>
              <Field label="전달자">{row.sender?.display_name ?? row.sender_name_raw ?? '-'}</Field>
              <Field label="담당자">{row.assignee?.display_name ?? row.assignee_name_raw ?? '-'}</Field>
              <Field label="태그">
                {row.tags.length ? row.tags.map((t) => (
                  <span key={t} className="chip mr-1">#{t}</span>
                )) : '-'}
              </Field>
              <Field label="공개">
                <ScopeBadge visibility={row.visibility} groupNames={row.group_names} />
              </Field>
            </dl>

            {editing && (
              <>
                <ScopePicker
                  visibility={(field('visibility', row.visibility) as Visibility)}
                  groupIds={(field('group_ids', row.group_ids) as number[]) ?? []}
                  currentNames={row.group_names}
                  onChange={(next) => {
                    set('visibility', next.visibility)
                    set('group_ids', next.group_ids)
                  }}
                />
                {/* 담당자 · 확인자가 그 그룹 사람이 아니면 저장 전에 알려 준다(§3) */}
                <ScopeWarning
                  visibility={(field('visibility', row.visibility) as Visibility)}
                  groupIds={(field('group_ids', row.group_ids) as number[]) ?? []}
                  userIds={[row.assignee?.id, row.checker?.id, row.sender?.id]}
                />
              </>
            )}

            <ParticipantsPanel handoverId={row.id} canEdit={canEdit} />
            <AnalysisRequest handoverId={row.id} />
            <RelatedKnowledge handoverId={row.id} title={row.title} />

            <section>
              <h3 className="text-ink-muted mb-1">내용</h3>
              {editing ? (
                <textarea className="input w-full h-40 py-1 resize-y"
                          value={String(field('content', row.content) ?? '')}
                          onChange={(e) => set('content', e.target.value)} />
              ) : (
                <p className="whitespace-pre-wrap break-words">{row.content || '(없음)'}</p>
              )}
            </section>

            <section>
              <h3 className="text-ink-muted mb-1">비고</h3>
              {editing ? (
                <textarea className="input w-full h-20 py-1 resize-y"
                          value={String(field('remark', row.remark) ?? '')}
                          onChange={(e) => set('remark', e.target.value)} />
              ) : (
                <p className="whitespace-pre-wrap break-words">{row.remark || '(없음)'}</p>
              )}
            </section>

            <section>
              <h3 className="text-ink-muted mb-1">확인 현황</h3>
              {row.acknowledgements.length === 0 && <p className="text-ink-faint">확인 기록 없음</p>}
              <ul className="space-y-0.5">
                {row.acknowledgements.map((a) => (
                  <li key={a.user_id} className="flex items-center gap-2">
                    <span className="text-ink-muted">{a.user?.display_name ?? `#${a.user_id}`}</span>
                    {a.state === 'ACKED' && (
                      <span className="text-state-done">✔ v{a.acked_version_no} 확인</span>
                    )}
                    {a.state === 'REACK_REQUIRED' && (
                      <span className="text-state-check">
                        ⚠ v{a.acked_version_no} 확인 후 변경됨
                        {a.stale_reason?.length ? ` (${a.stale_reason.map(fieldLabel).join(', ')})` : ''}
                      </span>
                    )}
                    {a.state === 'PENDING' && <span className="text-state-wait">○ 대기</span>}
                  </li>
                ))}
              </ul>
            </section>

            {editing && (
              <div className="space-y-1 border-t border-surface-border pt-2">
                <label className="text-ink-muted" htmlFor="change-reason">변경 사유 (선택)</label>
                <input id="change-reason" className="input w-full" value={reason}
                       placeholder="왜 바꾸는지 적어두면 나중에 감사에 도움이 됩니다"
                       onChange={(e) => setReason(e.target.value)} />
              </div>
            )}
          </>
        )}

        {tab === 'versions' && (
          <VersionHistory handoverId={handoverId}
                          currentVersion={row.current_version_no} canEdit={canEdit} />
        )}

        {tab === 'tasks' && (
          <HandoverTasks handoverId={handoverId} canCreate={!!me?.permissions.includes('task:create') && !row.is_deleted}
                         onCreate={() => setCreatingTask(true)} />
        )}

        {tab === 'schedules' && (
          <LinkedSchedules handover={{ id: row.id, title: row.title }}
                           canCreate={!!me?.permissions.includes('schedule:create') && !row.is_deleted} />
        )}

        {tab === 'comments' && (
          <HandoverComments handoverId={handoverId}
                            canWrite={!!me?.permissions.includes('handover:comment') && !row.is_deleted} />
        )}

        {tab === 'files' && (
          <Attachments entityType="HANDOVER" entityId={handoverId} canUpload={canEdit && !row.is_deleted}
                       invalidate={[['handover', handoverId], ['timeline', handoverId]]} />
        )}

        {tab === 'timeline' && <Timeline handoverId={handoverId} />}
      </div>

      {/* 하단 액션 */}
      <div className="px-3 py-2 border-t border-surface-border flex items-center gap-2">
        {editing ? (
          <>
            <button className="btn" onClick={() => { setEditing(false); setDraft({}) }}>
              취소
            </button>
            <span className="flex-1" />
            <button className="btn btn-primary" disabled={save.isPending || !Object.keys(draft).length}
                    onClick={() => save.mutate()}>
              저장 (새 버전 v{row.current_version_no + 1})
            </button>
          </>
        ) : (
          <>
            <button className="btn" disabled={ack.isPending || myAck?.state === 'ACKED'}
                    onClick={() => ack.mutate()}>
              <Check size={12} />
              {myAck?.state === 'ACKED' ? `확인함 (v${myAck.acked_version_no})` : '확인(Ack)'}
            </button>
            {myAck?.state === 'REACK_REQUIRED' && (
              <span className="text-state-check">확인 이후 내용이 바뀌었습니다</span>
            )}
            {ackHeld && (
              <span role="alert" className="text-state-check">
                보는 사이에 v{ackHeld.current} 로 바뀌었습니다
                {ackHeld.fields.length > 0 && ` (${ackHeld.fields.map(fieldLabel).join(', ')})`}
                {' '}— 내용을 확인한 뒤 다시 누르십시오
              </span>
            )}
          </>
        )}
      </div>

      {confirmDelete && (
        <ConfirmDialog title={`인수인계 #${row.id} 을(를) 삭제합니다`} confirmLabel="삭제" danger
                       busy={remove.isPending} input={{ label: '삭제 사유', required: true, placeholder: '예: 중복 등록' }}
                       onCancel={() => setConfirmDelete(false)}
                       onConfirm={(why) => { setConfirmDelete(false); remove.mutate(why) }}>
          <p>목록에서 사라지고, 관리자는 복구할 수 있습니다. 사유는 기록으로 남습니다.</p>
        </ConfirmDialog>
      )}

      {creatingTask && (
        <TaskCreateDialog handover={{ id: row.id, title: row.title, company: row.company?.name }}
                          onClose={() => setCreatingTask(false)} onCreated={() => setTab('tasks')} />
      )}

      {conflict && (
        <ConflictDialog detail={conflict} mine={draft}
                        onCancel={() => setConflict(null)}
                        onReload={() => {
                          setConflict(null); setEditing(false); setDraft({})
                          qc.invalidateQueries({ queryKey: ['handover', handoverId] })
                        }} />
      )}
    </aside>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </>
  )
}

function Timeline({ handoverId }: { handoverId: number }) {
  const { data } = useQuery({
    queryKey: ['timeline', handoverId],
    queryFn: () => handoverApi.timeline(handoverId),
  })
  const KIND_LABEL: Record<string, string> = {
    VERSION: '버전', ACK: '확인', REACK_REQUIRED: '재확인 필요', COMMENT: '댓글',
    TRANSFER: '교대 인계', TASK: '할일', TASK_DONE: '할일 완료', SCHEDULE: '일정', ATTACHMENT: '첨부',
  }
  return (
    <ul className="space-y-1">
      {(data ?? []).map((e, i) => (
        <li key={i} className="flex gap-2 border-l-2 border-surface-border pl-2 py-0.5">
          <span className="text-ink-faint tabular-nums shrink-0">
            {new Date(e.at).toLocaleString('ko-KR', {
              month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
            })}
          </span>
          <span className="chip h-5 shrink-0">{KIND_LABEL[e.kind] ?? e.kind}</span>
          <span className="truncate">{e.title}</span>
        </li>
      ))}
      {data?.length === 0 && <li className="text-ink-faint">이력이 없습니다.</li>}
    </ul>
  )
}

/** 이 인수인계에 딸린 할일(FR-D-06). 누르면 할일 화면에서 연다. */
function HandoverTasks({ handoverId, canCreate, onCreate }: { handoverId: number; canCreate: boolean; onCreate: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['handover-tasks', handoverId], queryFn: () => taskApi.forHandover(handoverId),
  })
  return (
    <div className="space-y-2">
      <div className="flex items-center">
        <p className="text-ink-muted text-sm flex-1">인수인계는 사실 기록, 할일은 해야 할 일입니다. 할일을 바꿔도 인수인계 버전은 그대로입니다.</p>
        {canCreate && <button className="btn btn-sm btn-primary shrink-0" onClick={onCreate}><Plus size={12} /> 할일 만들기</button>}
      </div>
      <ul className="space-y-1">
        {(data ?? []).map((t) => (
          <li key={t.id}>
            <Link to={`/tasks?id=${t.id}`} className="card px-2 py-1.5 flex items-center gap-2 hover:border-brand/50">
              <span className={`text-sm shrink-0 ${STATUS_TONE[t.status]}`}>{STATUS_LABEL[t.status]}</span>
              <span className="flex-1 truncate">{t.title}</span>
              <span className="text-xs text-ink-muted shrink-0">{t.assignee?.display_name ?? '(미지정)'}</span>
              {t.due_date && (
                <span className={`text-xs tabular-nums shrink-0 ${t.is_overdue ? 'text-state-urgent font-medium' : 'text-ink-muted'}`}>
                  {t.due_date.slice(5).replace('-', '/')}
                </span>
              )}
              {t.checklist_total > 0 && <span className="text-xs tabular-nums text-ink-faint shrink-0">{t.checklist_done}/{t.checklist_total}</span>}
            </Link>
          </li>
        ))}
        {!isLoading && data?.length === 0 && <li className="text-ink-faint">연결된 할일이 없습니다.</li>}
      </ul>
    </div>
  )
}
