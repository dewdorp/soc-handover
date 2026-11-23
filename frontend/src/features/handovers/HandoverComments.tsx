/**
 * 인수인계 댓글 — 본문을 바꾸지 않고 덧붙이는 후속 분석 · 질문 · 진행 메모.
 *
 * 댓글은 인계 원문과 따로다: 써도 고쳐도 버전이 오르지 않고 인수 확인이 풀리지 않는다.
 * 표 · 스크린샷 · 로그 블록을 넣을 수 있지만 도구는 본문보다 적게(compact) 둔다.
 * 댓글에 붙인 그림은 그 인계에 묶여, 인계를 볼 수 있는 사람만 본다.
 * 쓰기 · 고치기 · 지우기는 감사로그에 남는다. 고치기는 쓴 사람만, 지우기는 쓴 사람이나 근무 관리자 이상.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import LazyRichEditor from '@/features/richtext/LazyRichEditor'
import RichView from '@/features/richtext/RichView'
import { isEmptyDoc, type RichDoc } from '@/features/richtext/doc'
import { adminApi, type HandoverComment } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

export default function HandoverComments({ handoverId, canWrite }: { handoverId: number; canWrite: boolean }) {
  const qc = useQueryClient()
  const [doc, setDoc] = useState<RichDoc | null>(null)
  const [composerKey, setComposerKey] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [editing, setEditing] = useState<{ comment: HandoverComment; doc: RichDoc | null } | null>(null)
  const [editUploading, setEditUploading] = useState(false)
  const [removing, setRemoving] = useState<HandoverComment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['comments', handoverId], queryFn: () => adminApi.comments(handoverId),
  })

  const composing = Boolean(doc && !isEmptyDoc(doc)) || Boolean(editing?.doc)
  // 새로고침 · 탭 닫기로 쓰던 댓글이 사라지지 않게
  useEffect(() => {
    if (!composing) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [composing])

  const refresh = () => {
    for (const k of [['comments', handoverId], ['handover', handoverId], ['timeline', handoverId]]) qc.invalidateQueries({ queryKey: k })
  }
  const fail = (err: unknown) => setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')
  const add = useMutation({
    mutationFn: () => adminApi.addComment(handoverId, { body_doc: doc }),
    onSuccess: () => { setDoc(null); setComposerKey((k) => k + 1); setError(null); refresh() }, onError: fail,
  })
  const edit = useMutation({
    mutationFn: (e: { id: number; doc: RichDoc }) => adminApi.editComment(e.id, { body_doc: e.doc }),
    onSuccess: () => { setEditing(null); setError(null); refresh() }, onError: fail,
  })
  const remove = useMutation({
    mutationFn: (id: number) => adminApi.deleteComment(id),
    onSuccess: () => { setRemoving(null); refresh() }, onError: (err) => { setRemoving(null); fail(err) },
  })

  const canPost = Boolean(doc && !isEmptyDoc(doc)) && !uploading && !add.isPending
  const post = () => { if (canPost) add.mutate() }
  const saveEdit = () => {
    if (editing?.doc && !isEmptyDoc(editing.doc) && !editUploading && !edit.isPending) {
      edit.mutate({ id: editing.comment.id, doc: editing.doc })
    }
  }

  return (
    <div className="space-y-3">
      {isLoading && <p className="text-ink-faint">불러오는 중…</p>}
      {isError && (
        <p role="alert" className="text-sm text-state-urgent">
          댓글을 불러오지 못했습니다. <button className="btn btn-sm" onClick={() => refetch()}>다시 시도</button>
        </p>
      )}
      {data && (
        <ul className="space-y-2">
          {data.map((c) => (
            <li key={c.id} className="rounded border border-surface-border px-2.5 py-1.5 min-w-0">
              <div className="flex items-baseline gap-2 text-sm">
                <span className="font-medium">{c.author ?? '알 수 없음'}</span>
                <span className="text-ink-faint tabular-nums">{format(parseISO(c.created_at), 'MM-dd HH:mm')}</span>
                {c.is_edited && (
                  <span className="text-xs text-ink-faint"
                        title={c.edited_at ? `고친 시각 ${format(parseISO(c.edited_at), 'yyyy-MM-dd HH:mm')}` : undefined}>
                    (고침)
                  </span>
                )}
                <span className="flex-1" />
                {c.can_edit && editing?.comment.id !== c.id && (
                  <button className="text-xs text-ink-muted hover:text-ink" onClick={() => setEditing({ comment: c, doc: null })}>고치기</button>
                )}
                {c.can_delete && (
                  <button className="text-xs text-ink-muted hover:text-state-urgent" onClick={() => setRemoving(c)}>지우기</button>
                )}
              </div>
              {editing?.comment.id === c.id ? (
                <div className="mt-1 space-y-1">
                  <LazyRichEditor variant="compact" value={c.body_doc} fallbackText={c.body} autoFocus
                                  ariaLabel="댓글 고치기" onChange={(d) => setEditing({ comment: c, doc: d })}
                                  onBusyChange={setEditUploading} onSubmitShortcut={saveEdit} />
                  <div className="flex gap-1 justify-end">
                    <button className="btn btn-sm" onClick={() => setEditing(null)}>취소</button>
                    <button className="btn btn-sm btn-primary"
                            disabled={!editing.doc || isEmptyDoc(editing.doc) || editUploading || edit.isPending}
                            onClick={saveEdit}>{editUploading ? '그림 올리는 중…' : '저장'}</button>
                  </div>
                </div>
              ) : (
                <RichView doc={c.body_doc} text={c.body} className="mt-0.5" />
              )}
            </li>
          ))}
          {data.length === 0 && <li className="text-ink-faint">댓글이 없습니다.</li>}
        </ul>
      )}

      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}
      {canWrite && (
        <div className="space-y-1">
          <LazyRichEditor key={composerKey} variant="compact" value={null} onChange={setDoc}
                          onBusyChange={setUploading} onSubmitShortcut={post} ariaLabel="새 댓글"
                          placeholder="댓글 — 본문 · 확인 상태는 바뀌지 않습니다. 스크린샷은 Ctrl+V" />
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-faint">Ctrl+Enter 로 등록</span>
            <span className="flex-1" />
            <button className="btn btn-sm btn-primary" disabled={!canPost} onClick={post}>
              {uploading ? '그림 올리는 중…' : add.isPending ? '등록하는 중…' : '댓글 등록'}
            </button>
          </div>
        </div>
      )}

      {removing && (
        <ConfirmDialog title="댓글을 지웁니다" confirmLabel="지우기" danger busy={remove.isPending}
                       onCancel={() => setRemoving(null)} onConfirm={() => remove.mutate(removing.id)}>
          <p className="line-clamp-3 whitespace-pre-wrap">{removing.body}</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
