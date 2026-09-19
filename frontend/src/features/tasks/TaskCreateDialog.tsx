/**
 * 할일 만들기 (FR-D-04·06).
 *
 * handover 를 주면 '인수인계에서 바로 만들기'다 — 관계사·연결은 인수인계에서 가져오고,
 * 제목·내용·중요도는 비워 두면 서버가 인수인계 값으로 채운다(ASSUMPTIONS B-11).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { referenceApi } from '@/services/api/reference'
import { TASK_QUERY_KEYS, taskApi, type TaskDetail, type TaskInput } from '@/services/api/tasks'

interface Props {
  handover?: { id: number; title: string; company?: string | null }
  onClose: () => void
  onCreated?: (task: TaskDetail) => void
}

export default function TaskCreateDialog({ handover, onClose, onCreated }: Props) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const { data: users } = useQuery({ queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000 })
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 60_000, enabled: !handover })
  const { data: priorities } = useQuery({ queryKey: ['priorities'], queryFn: referenceApi.priorities, staleTime: 300_000 })
  const [form, setForm] = useState({
    title: '', description: '', assignee_id: '', due_date: '', priority_code: '', company_id: '', checklist: '',
  })
  const [error, setError] = useState<string | null>(null)
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }))

  const create = useMutation({
    mutationFn: () => {
      const checklist = form.checklist.split('\n').map((s) => s.trim()).filter(Boolean)
      const body: Partial<TaskInput> = {
        assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
        due_date: form.due_date || null,
        checklist,
      }
      if (form.title.trim()) body.title = form.title.trim()
      if (form.description.trim()) body.description = form.description.trim()
      if (form.priority_code) body.priority_code = form.priority_code
      if (handover) return taskApi.quickAdd(handover.id, body)
      return taskApi.create({
        ...body, title: form.title.trim(),
        company_id: form.company_id ? Number(form.company_id) : null,
      } as TaskInput)
    },
    onSuccess: (task) => {
      for (const key of TASK_QUERY_KEYS) qc.invalidateQueries({ queryKey: [key] })
      onCreated?.(task)
      onClose()
    },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '할일을 만들지 못했습니다.'),
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!handover && !form.title.trim()) {
      setError('제목은 필수입니다.')
      return
    }
    create.mutate()
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4"
         role="dialog" aria-modal="true" aria-labelledby="task-create-title">
      <form onSubmit={submit} className="card w-[520px] max-w-full shadow-xl p-4 space-y-2.5">
        <div className="flex items-center">
          <h2 id="task-create-title" className="font-medium text-md flex-1">
            {handover ? '이 인수인계로 할일 만들기' : '할일 만들기'}
          </h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>
        {handover && (
          <p className="text-sm bg-brand-soft rounded px-2 py-1">
            <span className="tabular-nums text-ink-faint mr-1">#{handover.id}</span>{handover.title}
            {handover.company && <span className="text-ink-muted"> · {handover.company}</span>}
            <span className="block text-xs text-ink-muted">관계사·연결은 자동. 제목·내용·중요도를 비우면 인수인계 값을 씁니다.</span>
          </p>
        )}

        <Labeled label={handover ? '제목' : '제목 *'}>
          <input className="input w-full" value={form.title} autoFocus
                 placeholder={handover ? handover.title : '무엇을 해야 하나요?'}
                 onChange={(e) => set('title', e.target.value)} />
        </Labeled>

        <div className="grid grid-cols-2 gap-2">
          <Labeled label="담당자">
            <select className="input w-full" value={form.assignee_id} onChange={(e) => set('assignee_id', e.target.value)}>
              <option value="">나 ({me?.display_name})</option>
              {(users ?? []).filter((u) => u.id !== me?.id).map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </Labeled>
          <Labeled label="마감일">
            <input type="date" className="input w-full" value={form.due_date} onChange={(e) => set('due_date', e.target.value)} />
          </Labeled>
          <Labeled label="중요도">
            <select className="input w-full" value={form.priority_code} onChange={(e) => set('priority_code', e.target.value)}>
              <option value="">{handover ? '(인수인계와 같게)' : '보통'}</option>
              {(priorities ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </select>
          </Labeled>
          {!handover && (
            <Labeled label="관계사">
              <select className="input w-full" value={form.company_id} onChange={(e) => set('company_id', e.target.value)}>
                <option value="">(없음)</option>
                {(companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Labeled>
          )}
        </div>

        <Labeled label="내용">
          <textarea className="input w-full h-20 py-1 resize-y" value={form.description}
                    placeholder={handover ? '(비우면 인수인계 내용 앞부분)' : ''}
                    onChange={(e) => set('description', e.target.value)} />
        </Labeled>
        <Labeled label="체크리스트 (한 줄에 하나)">
          <textarea className="input w-full h-16 py-1 resize-y" value={form.checklist}
                    placeholder={'차단 목록 확인\n고객사 통보'} onChange={(e) => set('checklist', e.target.value)} />
        </Labeled>

        {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>취소</button>
          <button className="btn btn-primary" disabled={create.isPending}>만들기</button>
        </div>
      </form>
    </div>
  )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-0.5">
      <span className="text-ink-muted text-sm">{label}</span>
      {children}
    </label>
  )
}
