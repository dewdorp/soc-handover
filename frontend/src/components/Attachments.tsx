/**
 * 첨부 목록 · 올리기 · 내려받기 · 지우기 — 인수인계와 할일이 같이 쓴다.
 *
 * 확장자 · 크기는 서버가 최종 검사하고(관리 설정 attachment.*), 여기서는 올리기 전에 한 번 더 알려준다.
 * 내려받기는 같은 출처 링크라 로그인 쿠키가 따라간다. 받을 때마다 감사로그에 남는다.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { Download, Paperclip, ShieldCheck, Trash2, Upload } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useFeatures } from '@/hooks/useAuth'
import { adminApi, formatBytes, type AttachmentRow, type EntityType } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

interface Props {
  entityType: EntityType
  entityId: number
  canUpload: boolean
  /** 개수가 바뀌었을 때(탭 제목의 숫자 등) 다시 불러올 쿼리 */
  invalidate?: unknown[][]
}

export default function Attachments({ entityType, entityId, canUpload, invalidate = [] }: Props) {
  const qc = useQueryClient()
  const { data: features } = useFeatures()
  const inputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [removing, setRemoving] = useState<AttachmentRow | null>(null)
  const key = ['attachments', entityType, entityId]
  const { data, isLoading } = useQuery({ queryKey: key, queryFn: () => adminApi.attachments(entityType, entityId) })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: key })
    for (const k of invalidate) qc.invalidateQueries({ queryKey: k })
  }

  const allowed = (features?.attachment.allowed_ext ?? []).map((x) => x.toLowerCase().replace(/^\./, ''))
  const maxMb = features?.attachment.max_size_mb ?? 0

  /** 여러 파일을 차례로 올린다. 하나가 막혀도 나머지는 계속한다. */
  const uploadAll = async (files: File[]) => {
    setError(null)
    const problems: string[] = []
    for (const f of files) {
      const ext = f.name.includes('.') ? f.name.split('.').pop()!.toLowerCase() : ''
      if (allowed.length && !allowed.includes(ext)) { problems.push(`${f.name}: 허용하지 않는 형식입니다(.${ext || '확장자 없음'}).`); continue }
      if (maxMb && f.size > maxMb * 1024 * 1024) { problems.push(`${f.name}: ${maxMb}MB 를 넘습니다.`); continue }
      if (f.size === 0) { problems.push(`${f.name}: 빈 파일입니다.`); continue }
      setBusy(f.name)
      try { await adminApi.uploadAttachment(entityType, entityId, f) }
      catch (err) { problems.push(`${f.name}: ${err instanceof ApiRequestError ? err.message : '올리지 못했습니다.'}`) }
    }
    setBusy(null)
    if (problems.length) setError(problems.join('\n'))
    refresh()
  }

  const remove = useMutation({
    mutationFn: (id: number) => adminApi.deleteAttachment(id),
    onSuccess: () => { setRemoving(null); refresh() },
    onError: (err) => { setRemoving(null); setError(err instanceof ApiRequestError ? err.message : '지우지 못했습니다.') },
  })

  return (
    <div className="space-y-2">
      {canUpload && (
        <div className={`rounded border border-dashed px-3 py-2.5 text-sm flex flex-wrap items-center gap-2 ${dragging ? 'border-brand bg-brand-soft' : 'border-surface-border'}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); if (!busy) uploadAll([...e.dataTransfer.files]) }}>
          <button className="btn btn-sm" disabled={!!busy} onClick={() => inputRef.current?.click()}><Upload size={12} /> 파일 올리기</button>
          <span className="text-ink-muted">{busy ? `올리는 중… ${busy}` : '또는 여기로 끌어다 놓기'}</span>
          <span className="w-full text-xs text-ink-faint">
            {allowed.length ? `허용: ${allowed.join(', ')}` : ''}{maxMb ? ` · 파일당 ${maxMb}MB 까지` : ''}
          </span>
          <input ref={inputRef} type="file" multiple hidden aria-label="첨부 파일"
                 accept={allowed.map((x) => `.${x}`).join(',') || undefined}
                 onChange={(e) => { const fs = [...(e.target.files ?? [])]; e.target.value = ''; if (fs.length) uploadAll(fs) }} />
        </div>
      )}
      {error && <p role="alert" className="text-sm text-state-urgent whitespace-pre-line">{error}</p>}

      {isLoading ? <p className="text-ink-faint">불러오는 중…</p> : (
        <ul className="divide-y divide-surface-border/70">
          {data?.map((a) => (
            <li key={a.id} className="py-1.5 flex items-center gap-2 min-w-0">
              <Paperclip size={13} className="text-ink-faint shrink-0" />
              <div className="min-w-0 flex-1">
                <a href={adminApi.attachmentUrl(a.id)} className="text-brand hover:underline break-all" download>{a.name}</a>
                <p className="text-xs text-ink-faint">
                  {formatBytes(a.size)} · {a.uploaded_by ?? '알 수 없음'} · {format(parseISO(a.created_at), 'MM-dd HH:mm')}
                  {a.scan_status === 'CLEAN'
                    ? <span className="text-state-done"> · <ShieldCheck size={11} className="inline -mt-0.5" /> 검사 통과</span>
                    : <span> · 악성코드 검사 안 함</span>}
                </p>
              </div>
              <a href={adminApi.attachmentUrl(a.id)} download className="text-ink-faint hover:text-ink shrink-0" aria-label={`${a.name} 내려받기`}><Download size={14} /></a>
              {a.can_delete && (
                <button className="text-ink-faint hover:text-state-urgent shrink-0" aria-label={`${a.name} 지우기`} onClick={() => setRemoving(a)}><Trash2 size={14} /></button>
              )}
            </li>
          ))}
          {data?.length === 0 && <li className="py-2 text-ink-faint">첨부가 없습니다.</li>}
        </ul>
      )}

      {removing && (
        <ConfirmDialog title="첨부를 지웁니다" confirmLabel="지우기" danger busy={remove.isPending}
                       onCancel={() => setRemoving(null)} onConfirm={() => remove.mutate(removing.id)}>
          <p className="break-all">{removing.name}</p>
          <p className="text-ink-muted">목록에서 사라집니다. 지운 기록은 감사로그에 남습니다.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
