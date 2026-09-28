/**
 * 비밀번호 항목 등록 · 수정 + 변경 이력.
 *
 * 수정에서 비밀번호 칸을 비워 두면 지금 값을 그대로 둔다(빈 값으로 덮어쓰지 않는다).
 * 비밀번호를 바꾸면 바꾸기 전 값이 이력에 남아, 장비에 새 값이 안 먹었을 때 되돌릴 수 있다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { Eye, Trash2 } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import RevealDialog from '@/features/credentials/RevealDialog'
import { ApiRequestError } from '@/services/api/client'
import { credentialApi, type Credential, type CredentialScope } from '@/services/api/credentials'
import { referenceApi } from '@/services/api/reference'

const FIELD_LABEL: Record<string, string> = {
  secret: '비밀번호', device_name: '장비명', access_method: '접속 방법',
  username: '계정', company_id: '관계사', note: '메모', scope: '공개 범위',
}

interface Props {
  /** 없으면 새로 등록 */
  credential: Credential | null
  onClose: () => void
}

export default function CredentialDialog({ credential, onClose }: Props) {
  const qc = useQueryClient()
  const editing = credential != null
  const [form, setForm] = useState({
    scope: (credential?.scope ?? 'SHARED') as CredentialScope,
    company_id: credential?.company_id ?? null,
    device_name: credential?.device_name ?? '',
    access_method: credential?.access_method ?? '',
    username: credential?.username ?? '',
    secret: '',
    note: credential?.note ?? '',
    change_note: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [revealVersion, setRevealVersion] = useState<number | null>(null)

  const { data: companies } = useQuery({
    queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 60_000,
  })
  const { data: history } = useQuery({
    queryKey: ['credential-history', credential?.id], enabled: editing,
    queryFn: () => credentialApi.history(credential!.id),
  })

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const done = () => {
    qc.invalidateQueries({ queryKey: ['credentials'] })
    qc.invalidateQueries({ queryKey: ['credential-history', credential?.id] })
    onClose()
  }
  const fail = (err: unknown) =>
    setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.')

  const save = useMutation({
    mutationFn: () => {
      const body = {
        scope: form.scope, company_id: form.company_id, device_name: form.device_name.trim(),
        access_method: form.access_method.trim() || null,
        username: form.username.trim() || null, note: form.note.trim() || null,
      }
      if (!editing) return credentialApi.create({ ...body, secret: form.secret })
      return credentialApi.update(credential.id, {
        ...body,
        // 비워 두면 지금 비밀번호를 그대로 둔다
        ...(form.secret ? { secret: form.secret } : {}),
        ...(form.change_note.trim() ? { change_note: form.change_note.trim() } : {}),
      })
    },
    onSuccess: done, onError: fail,
  })
  const remove = useMutation({
    mutationFn: () => credentialApi.remove(credential!.id), onSuccess: done, onError: fail,
  })

  const blocked = !form.device_name.trim() || (!editing && !form.secret)

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/30 p-4" role="dialog"
         aria-modal="true" aria-labelledby="cred-title" onClick={onClose}>
      <div className="card w-[560px] max-w-full max-h-full overflow-auto shadow-xl p-4 space-y-3"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <h2 id="cred-title" className="font-medium flex-1">
            {editing ? '비밀번호 수정' : '비밀번호 등록'}
          </h2>
          <button onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink">✕</button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="block space-y-0.5">
            <span className="text-ink-muted">관계사</span>
            <select className="input w-full" value={form.company_id ?? ''}
                    onChange={(e) => set('company_id', e.target.value ? Number(e.target.value) : null)}>
              <option value="">(미지정)</option>
              {(companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="block space-y-0.5">
            <span className="text-ink-muted">공개 범위</span>
            <select className="input w-full" value={form.scope}
                    onChange={(e) => set('scope', e.target.value as CredentialScope)}>
              <option value="SHARED">공용 — 교대 근무자 전원이 봅니다</option>
              <option value="PERSONAL">개인 — 나만 봅니다</option>
            </select>
          </label>
        </div>

        <label className="block space-y-0.5">
          <span className="text-ink-muted">장비명 *</span>
          <input className="input w-full" value={form.device_name} placeholder="예: 본사 방화벽-01"
                 onChange={(e) => set('device_name', e.target.value)} />
        </label>

        <label className="block space-y-0.5">
          <span className="text-ink-muted">접속 방법</span>
          <input className="input w-full" value={form.access_method}
                 placeholder="예: SSH 10.0.0.1:22 · 웹 https://10.0.0.1 · 콘솔"
                 onChange={(e) => set('access_method', e.target.value)} />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block space-y-0.5">
            <span className="text-ink-muted">계정</span>
            <input className="input w-full" value={form.username} autoComplete="off"
                   onChange={(e) => set('username', e.target.value)} />
          </label>
          <label className="block space-y-0.5">
            <span className="text-ink-muted">비밀번호 {editing ? '' : '*'}</span>
            <input className="input w-full" type="password" value={form.secret} autoComplete="new-password"
                   placeholder={editing ? '비워 두면 그대로' : ''}
                   onChange={(e) => set('secret', e.target.value)} />
          </label>
        </div>

        <label className="block space-y-0.5">
          <span className="text-ink-muted">메모</span>
          <textarea className="input w-full h-14 py-1 resize-y" value={form.note}
                    placeholder="예: 분기 점검 때 변경, 담당 김철수"
                    onChange={(e) => set('note', e.target.value)} />
        </label>

        {editing && form.secret && (
          <label className="block space-y-0.5">
            <span className="text-ink-muted">바꾸는 이유</span>
            <input className="input w-full" value={form.change_note} placeholder="예: 정기 교체"
                   onChange={(e) => set('change_note', e.target.value)} />
          </label>
        )}

        {editing && (history?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <span className="text-ink-muted">변경 이력</span>
            <ul className="divide-y divide-surface-border/70 border border-surface-border rounded">
              {history!.map((h) => (
                <li key={h.version_no} className="px-2 py-1 flex items-center gap-2 text-sm">
                  <span className="tabular-nums text-ink-faint shrink-0">v{h.version_no}</span>
                  <div className="min-w-0 flex-1">
                    <span>{h.changed_fields.map((f) => FIELD_LABEL[f] ?? f).join(' · ') || '변경'}</span>
                    <span className="text-ink-faint">
                      {' '}· {h.changed_by ?? '알 수 없음'} · {format(parseISO(h.changed_at), 'MM-dd HH:mm')}
                    </span>
                    {h.change_note && <div className="text-ink-muted">📝 {h.change_note}</div>}
                  </div>
                  {h.has_secret && (
                    <button className="btn btn-sm shrink-0" onClick={() => setRevealVersion(h.version_no)}>
                      <Eye size={12} /> 그때 값
                    </button>
                  )}
                </li>
              ))}
            </ul>
            <p className="text-xs text-ink-faint">
              옛 비밀번호는 최근 5개까지만 남습니다. 그때 값을 여는 것도 감사에 기록됩니다.
            </p>
          </div>
        )}

        {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}

        <div className="flex justify-end gap-2">
          {editing && credential.can_edit && (
            <button className="btn text-state-urgent mr-auto" onClick={() => setRemoving(true)}>
              <Trash2 size={13} /> 지우기
            </button>
          )}
          <button className="btn" onClick={onClose}>취소</button>
          <button className="btn btn-primary" disabled={blocked || save.isPending}
                  onClick={() => save.mutate()}>저장</button>
        </div>
      </div>

      {revealVersion != null && credential && (
        <RevealDialog credential={credential} versionNo={revealVersion}
                      onClose={() => setRevealVersion(null)} />
      )}
      {removing && (
        <ConfirmDialog title="이 비밀번호 항목을 지웁니다" confirmLabel="지우기" danger
                       busy={remove.isPending} onCancel={() => setRemoving(false)}
                       onConfirm={() => remove.mutate()}>
          <p className="break-all">{credential?.device_name}</p>
          <p className="text-ink-muted">목록에서 사라집니다. 지운 기록은 감사로그에 남습니다.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
