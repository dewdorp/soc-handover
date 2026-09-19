/**
 * 인수인계 댓글 — 본문을 바꾸지 않고 덧붙이는 이야기(질문 · 진행 메모).
 * 댓글은 버전을 올리지 않아 재확인을 부르지 않는다. 쓰기 · 고치기 · 지우기는 감사로그에 남는다.
 * 고치기는 쓴 사람만, 지우기는 쓴 사람이나 근무 관리자 이상.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { adminApi, type HandoverComment } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

export default function HandoverComments({ handoverId, canWrite }: { handoverId: number; canWrite: boolean }) {
  const qc = useQueryClient()
  const [body, setBody] = useState('')
  const [editing, setEditing] = useState<{ id: number; body: string } | null>(null)
  const [removing, setRemoving] = useState<HandoverComment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['comments', handoverId], queryFn: () => adminApi.comments(handoverId) })

  const refresh = () => {
    for (const k of [['comments', handoverId], ['handover', handoverId], ['timeline', handoverId]]) qc.invalidateQueries({ queryKey: k })
  }
  const fail = (err: unknown) => setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')
  const add = useMutation({
    mutationFn: () => adminApi.addComment(handoverId, body.trim()),
    onSuccess: () => { setBody(''); setError(null); refresh() }, onError: fail,
  })
  const edit = useMutation({
    mutationFn: (e: { id: number; body: string }) => adminApi.editComment(e.id, e.body.trim()),
    onSuccess: () => { setEditing(null); setError(null); refresh() }, onError: fail,
  })
  const remove = useMutation({
    mutationFn: (id: number) => adminApi.deleteComment(id),
    onSuccess: () => { setRemoving(null); refresh() }, onError: (err) => { setRemoving(null); fail(err) },
  })

  return (
    <div className="space-y-3">
      {isLoading ? <p className="text-ink-faint">불러오는 중…</p> : (
        <ul className="space-y-2">
          {data?.map((c) => (
            <li key={c.id} className="rounded border border-surface-border px-2.5 py-1.5">
              <div className="flex items-baseline gap-2 text-sm">
                <span className="font-medium">{c.author ?? '알 수 없음'}</span>
                <span className="text-ink-faint tabular-nums">{format(parseISO(c.created_at), 'MM-dd HH:mm')}</span>
                {c.is_edited && <span className="text-xs text-ink-faint" title={c.edited_at ? format(parseISO(c.edited_at), 'yyyy-MM-dd HH:mm') : undefined}>(고침)</span>}
                <span className="flex-1" />
                {c.can_edit && editing?.id !== c.id && <button className="text-xs text-ink-muted hover:text-ink" onClick={() => setEditing({ id: c.id, body: c.body })}>고치기</button>}
                {c.can_delete && <button className="text-xs text-ink-muted hover:text-state-urgent" onClick={() => setRemoving(c)}>지우기</button>}
              </div>
              {editing?.id === c.id ? (
                <div className="mt-1 space-y-1">
                  <textarea className="input w-full h-20 py-1 resize-y" value={editing.body} aria-label="댓글 고치기" autoFocus
                            onChange={(e) => setEditing({ id: c.id, body: e.target.value })}
                            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && editing.body.trim()) edit.mutate(editing) }} />
                  <div className="flex gap-1 justify-end">
                    <button className="btn btn-sm" onClick={() => setEditing(null)}>취소</button>
                    <button className="btn btn-sm btn-primary" disabled={!editing.body.trim() || edit.isPending} onClick={() => edit.mutate(editing)}>저장</button>
                  </div>
                </div>
              ) : (
                <p className="mt-0.5 whitespace-pre-wrap break-words">{c.body}</p>
              )}
            </li>
          ))}
          {data?.length === 0 && <li className="text-ink-faint">댓글이 없습니다.</li>}
        </ul>
      )}

      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}
      {canWrite && (
        <form className="space-y-1" onSubmit={(e) => { e.preventDefault(); if (body.trim()) add.mutate() }}>
          <textarea className="input w-full h-20 py-1 resize-y" placeholder="댓글 — 본문은 바뀌지 않고 확인 상태에도 영향이 없습니다." value={body}
                    aria-label="새 댓글" maxLength={4000} onChange={(e) => setBody(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && body.trim()) add.mutate() }} />
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-faint">Ctrl+Enter 로 등록</span>
            <span className="flex-1" />
            <button className="btn btn-sm btn-primary" disabled={!body.trim() || add.isPending}>댓글 등록</button>
          </div>
        </form>
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
