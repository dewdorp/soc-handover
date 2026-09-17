/**
 * 인수인계 상세 Drawer (UI_STRUCTURE §4).
 *
 * 목록 컨텍스트를 유지한 채 우측에서 열린다. 수정은 인라인 편집 + 변경 사유이고,
 * 저장은 expected_version 을 함께 보낸다 → 충돌 시 409 를 받아 다이얼로그를 띄운다.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Pin, Star, Trash2, X } from 'lucide-react'
import ConflictDialog from '@/features/handovers/ConflictDialog'
import VersionHistory, { fieldLabel } from '@/features/handovers/VersionHistory'
import { ApiRequestError } from '@/services/api/client'
import { handoverApi } from '@/services/api/handovers'
import { useMe } from '@/hooks/useAuth'
import type { Company, HandoverStatus, Priority } from '@/types/api'
import type { VersionConflictDetail } from '@/types/handover'

type Tab = 'detail' | 'versions' | 'timeline'

interface Props {
  handoverId: number
  companies: Company[]
  statuses: HandoverStatus[]
  priorities: Priority[]
  onClose: () => void
}

export default function HandoverDrawer({ handoverId, companies, statuses, priorities, onClose }: Props) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [tab, setTab] = useState<Tab>('detail')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [reason, setReason] = useState('')
  const [conflict, setConflict] = useState<VersionConflictDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

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
      if (e.key === 'Escape' && !conflict) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, conflict])

  const canEdit = useMemo(() => {
    if (!row || !me) return false
    if (me.permissions.includes('handover:update_any')) return true
    return row.created_by === me.id || row.assignee?.id === me.id
  }, [row, me])

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

  const ack = useMutation({
    mutationFn: () => handoverApi.acknowledge(handoverId),
    onSuccess: invalidate,
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
      <aside className="w-[520px] shrink-0 border-l border-surface-border bg-surface
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
    <aside className="w-[520px] shrink-0 border-l border-surface-border bg-surface
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
                    onClick={() => {
                      const why = window.prompt('삭제 사유를 입력하십시오. (필수)')
                      if (why && why.trim()) remove.mutate(why.trim())
                    }} aria-label="삭제"><Trash2 size={12} /></button>
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
      <nav className="flex gap-1 px-3 pt-2 border-b border-surface-border" role="tablist">
        {([['detail', '상세'], ['versions', '변경이력'], ['timeline', '전체 이력']] as const)
          .map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key}
                    onClick={() => setTab(key)}
                    className={`px-2 h-7 rounded-t border-b-2 ${tab === key
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
            </dl>

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
                    <span className="tabular-nums text-ink-muted">#{a.user_id}</span>
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
          </>
        )}
      </div>

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
