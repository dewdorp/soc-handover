/** 인수인계 등록. 필수는 관계사·제목뿐이고 나머지는 나중에 채울 수 있게 둔다. */
import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEscape } from '@/hooks/useHotkeys'
import { ApiRequestError } from '@/services/api/client'
import { handoverApi } from '@/services/api/handovers'
import ScopePicker, { type Visibility } from '@/features/handovers/ScopePicker'
import ScopeWarning from '@/features/handovers/ScopeWarning'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import LazyRichEditor from '@/features/richtext/LazyRichEditor'
import { isEmptyDoc, type RichDoc } from '@/features/richtext/doc'
import { referenceApi } from '@/services/api/reference'
import type { Company, HandoverStatus, Priority } from '@/types/api'

export interface HandoverDraft {
  title?: string
  content?: string
}

interface Props {
  /** 다른 화면(개인 메모 등)에서 넘겨 준 초안. 고른 글만 들어온다. */
  draft?: HandoverDraft
  companies: Company[]
  statuses: HandoverStatus[]
  priorities: Priority[]
  onClose: () => void
  onCreated: (id: number) => void
}

export default function CreateHandoverDialog(
  { draft, companies, statuses, priorities, onClose, onCreated }: Props,
) {
  const [doc, setDoc] = useState<RichDoc | null>(null)
  const [uploading, setUploading] = useState(false)
  const [askClose, setAskClose] = useState(false)
  const [form, setForm] = useState({
    company_id: null as number | null,
    title: draft?.title ?? '', content: draft?.content ?? '', remark: '',
    status_code: 'NEW', priority_code: 'NORMAL',
    work_date: '', assignee_id: '', tags: '',
    is_important: false,
  })
  const [scope, setScope] = useState<{ visibility: Visibility; group_ids: number[] }>(
    { visibility: 'ALL', group_ids: [] })
  // 기본 그룹을 한 번만 채운다. 손대지 않고 올려도 서버가 같은 값을 쓰므로 결과는 같다.
  const picked = scope.group_ids
  const companyId = form.company_id ?? companies[0]?.id
  const [error, setError] = useState<string | null>(null)

  // 표 · 스크린샷을 붙여 넣은 글이 실수로 닫혀 사라지지 않게 — 닫기 전에 묻는다.
  const dirty = Boolean(form.title.trim() || form.remark.trim() || form.tags.trim()
    || (doc && !isEmptyDoc(doc)))
  const requestClose = () => { if (dirty) setAskClose(true); else onClose() }
  useEscape(requestClose)
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const { data: users } = useQuery({
    queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000,
  })

  const create = useMutation({
    mutationFn: (selectedCompany: number) => handoverApi.create({
      company_id: selectedCompany,
      title: form.title.trim(),
      // 편집기에서 손댄 글은 서식 구조로, 손대지 않은 초안(개인 메모에서 넘어온 글)은 글 그대로.
      ...(doc ? { content_doc: doc } : { content: form.content }),
      remark: form.remark || null,
      status_code: form.status_code,
      priority_code: form.priority_code,
      work_date: form.work_date || null,
      assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
      is_important: form.is_important,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      visibility: scope.visibility,
      group_ids: scope.visibility === 'GROUPS' ? picked : [],
    }),
    onSuccess: (row) => onCreated(row.id),
    onError: (err) => setError(err instanceof ApiRequestError
      ? err.message : '등록하지 못했습니다.'),
  })

  const set = (key: string, value: unknown) => setForm((f) => ({ ...f, [key]: value }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!form.title.trim()) {
      setError('제목은 필수입니다.')
      return
    }
    if (companyId == null) {
      setError('관계사 목록에서 사용할 항목을 확인해 주세요.')
      return
    }
    if (uploading) {
      setError('그림을 올리는 중입니다. 끝난 뒤 등록하십시오.')
      return
    }
    create.mutate(companyId)
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4"
         role="dialog" aria-modal="true" aria-labelledby="create-title">
      <form onSubmit={submit} className="card w-[880px] max-w-full max-h-[94vh] overflow-y-auto shadow-xl p-4 space-y-2.5">
        <div className="flex items-center">
          <h2 id="create-title" className="font-medium text-md flex-1">인수인계 등록</h2>
          <button type="button" onClick={requestClose} aria-label="닫기"
                  className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Labeled label="관계사 *">
            <select className="input w-full" value={companyId ?? ''}
                    onChange={(e) => set('company_id', Number(e.target.value))}>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Labeled>
          <Labeled label="담당자">
            <select className="input w-full" value={form.assignee_id}
                    onChange={(e) => set('assignee_id', e.target.value)}>
              <option value="">(미지정)</option>
              {(users ?? []).map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </Labeled>
          <Labeled label="상태">
            <select className="input w-full" value={form.status_code}
                    onChange={(e) => set('status_code', e.target.value)}>
              {statuses.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </Labeled>
          <Labeled label="중요도">
            <select className="input w-full" value={form.priority_code}
                    onChange={(e) => set('priority_code', e.target.value)}>
              {priorities.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </select>
          </Labeled>
          <Labeled label="수행일">
            <input type="date" className="input w-full" value={form.work_date}
                   onChange={(e) => set('work_date', e.target.value)} />
          </Labeled>
          <Labeled label="태그 (쉼표 구분)">
            <input className="input w-full" value={form.tags} placeholder="방화벽, 긴급"
                   onChange={(e) => set('tags', e.target.value)} />
          </Labeled>
        </div>

        <Labeled label="제목 *">
          <input className="input w-full" value={form.title} autoFocus maxLength={300}
                 onChange={(e) => set('title', e.target.value)} />
        </Labeled>

        <div className="space-y-0.5" role="group" aria-label="내용">
          <span className="text-ink-muted">내용</span>
          <LazyRichEditor value={null} fallbackText={form.content} onChange={setDoc}
                          onBusyChange={setUploading} ariaLabel="인수인계 내용" />
        </div>

        <Labeled label="비고">
          <input className="input w-full" value={form.remark}
                 onChange={(e) => set('remark', e.target.value)} />
        </Labeled>

        <ScopePicker visibility={scope.visibility} groupIds={picked} onChange={setScope} />
        {/* 담당자가 그 그룹 사람이 아니면 저장 전에 알려 준다(§3) */}
        <ScopeWarning visibility={scope.visibility} groupIds={picked}
                      userIds={[form.assignee_id ? Number(form.assignee_id) : null]} />

        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={form.is_important}
                 onChange={(e) => set('is_important', e.target.checked)} />
          <span>중요 업무로 표시</span>
        </label>

        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border
                                     border-red-200 rounded px-2 py-1">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn" onClick={requestClose}>취소</button>
          <button className="btn btn-primary" disabled={create.isPending || uploading || companyId == null}>
            {create.isPending ? '등록하는 중…' : uploading ? '그림 올리는 중…' : '등록'}
          </button>
        </div>
      </form>
      {askClose && (
        <ConfirmDialog title="작성 중인 인수인계를 닫을까요?" confirmLabel="닫기" danger
                       onConfirm={() => { setAskClose(false); onClose() }} onCancel={() => setAskClose(false)}>
          아직 등록하지 않았습니다. 닫으면 쓴 내용과 붙여 넣은 그림이 사라집니다.
        </ConfirmDialog>
      )}
    </div>
  )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-0.5">
      <span className="text-ink-muted">{label}</span>
      {children}
    </label>
  )
}
