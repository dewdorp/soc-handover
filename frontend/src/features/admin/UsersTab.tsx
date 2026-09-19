/** 사용자 관리 — 등록 · 수정 · 역할 · 비활성화 · 비밀번호 초기화(임시 비밀번호는 한 번만 보여준다). */
import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { KeyRound, Plus, X } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useMe } from '@/hooks/useAuth'
import { useEscape } from '@/hooks/useHotkeys'
import { adminApi, type AdminUser } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

const ROLE_LABEL: Record<string, string> = { ADMIN: '관리자', MANAGER: '근무 관리자', ANALYST: '근무자' }

/** 정책(대·소문자 · 숫자 · 기호, 14자)을 만족하는 임시 비밀번호 — 브라우저의 암호학적 난수로. */
function tempPassword(): string {
  const sets = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnpqrstuvwxyz', '23456789', '#%+=!?']
  const all = sets.join('')
  const pick = (s: string) => s[crypto.getRandomValues(new Uint32Array(1))[0] % s.length]
  const chars = [...sets.map(pick), ...Array.from({ length: 10 }, () => pick(all))]
  for (let i = chars.length - 1; i > 0; i -= 1) {
    const j = crypto.getRandomValues(new Uint32Array(1))[0] % (i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]]
  }
  return chars.join('')
}

export default function UsersTab() {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [active, setActive] = useState<'' | 'true' | 'false'>('')
  const [editing, setEditing] = useState<AdminUser | 'new' | null>(null)
  const [resetting, setResetting] = useState<AdminUser | null>(null)
  const [issued, setIssued] = useState<{ username: string; password: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data, isFetching } = useQuery({
    queryKey: ['admin-users', q, role, active], queryFn: () => adminApi.users(q, role, active), placeholderData: keepPreviousData,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin-users'] })
  const fail = (err: unknown) => setError(err instanceof ApiRequestError ? err.message : '처리하지 못했습니다.')
  const toggle = useMutation({
    mutationFn: (u: AdminUser) => adminApi.updateUser(u.id, { is_active: !u.is_active }),
    onSuccess: () => { setError(null); refresh() }, onError: fail,
  })
  const reset = useMutation({
    mutationFn: (u: AdminUser) => adminApi.resetPassword(u.id),
    onSuccess: (res) => { setIssued({ username: res.username, password: res.temporary_password }); refresh() }, onError: fail,
  })

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <input className="input w-48" placeholder="이름 · 계정 · 메일" value={q} onChange={(e) => setQ(e.target.value)} aria-label="사용자 검색" />
        <select className="input" value={role} onChange={(e) => setRole(e.target.value)} aria-label="역할">
          <option value="">역할 전체</option>
          {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="input" value={active} onChange={(e) => setActive(e.target.value as typeof active)} aria-label="상태">
          <option value="">활성 · 비활성</option><option value="true">활성만</option><option value="false">비활성만</option>
        </select>
        <span className="text-sm text-ink-faint tabular-nums">{data ? `${data.total}명` : ''}</span>
        <span className="flex-1" />
        <button className="btn btn-sm btn-primary" onClick={() => setEditing('new')}><Plus size={12} /> 사용자</button>
      </div>
      {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}
      <div className={`overflow-auto border border-surface-border rounded bg-surface ${isFetching ? 'opacity-70' : ''}`}>
        <table className="w-full text-base whitespace-nowrap">
          <thead className="bg-surface-sunken text-ink-muted">
            <tr>{['이름', '계정', '역할', '팀', '상태', '마지막 로그인', ''].map((h) => <th key={h} className="text-left font-medium px-2 py-1">{h}</th>)}</tr>
          </thead>
          <tbody>
            {data?.items.map((u) => {
              const locked = u.locked_until && parseISO(u.locked_until) > new Date()
              return (
                <tr key={u.id} className={`border-t border-surface-border/60 ${u.is_active ? '' : 'text-ink-faint'}`}>
                  <td className="px-2 py-1 font-medium">{u.display_name}{u.id === me?.id && <span className="text-xs text-ink-faint"> (나)</span>}</td>
                  <td className="px-2 py-1 font-mono text-sm">{u.username}</td>
                  <td className="px-2 py-1">{ROLE_LABEL[u.role_code] ?? u.role_code}</td>
                  <td className="px-2 py-1">{u.team ?? '-'}</td>
                  <td className="px-2 py-1 space-x-1">
                    <span className={u.is_active ? 'text-state-done' : ''}>{u.is_active ? '활성' : '비활성'}</span>
                    {locked && <span className="chip h-5 text-state-urgent">잠김</span>}
                    {u.must_change_password && <span className="chip h-5">비밀번호 변경 대기</span>}
                  </td>
                  <td className="px-2 py-1 tabular-nums text-ink-muted">{u.last_login_at ? format(parseISO(u.last_login_at), 'yyyy-MM-dd HH:mm') : '-'}</td>
                  <td className="px-2 py-1 text-right space-x-1">
                    <button className="btn btn-sm" onClick={() => setEditing(u)}>수정</button>
                    <button className="btn btn-sm" onClick={() => setResetting(u)} title="임시 비밀번호 발급 · 잠금 해제"><KeyRound size={12} /> 초기화</button>
                    {u.id !== me?.id && (
                      <button className="btn btn-sm" disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>{u.is_active ? '비활성화' : '활성화'}</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {editing && <UserDialog user={editing === 'new' ? null : editing} isMe={editing !== 'new' && editing.id === me?.id}
                              onClose={() => setEditing(null)}
                              onSaved={(pw) => { setEditing(null); refresh(); if (pw) setIssued(pw) }} />}
      {resetting && (
        <ConfirmDialog title={`${resetting.display_name}(${resetting.username}) 비밀번호를 초기화합니다`} confirmLabel="초기화" danger
                       busy={reset.isPending} onCancel={() => setResetting(null)}
                       onConfirm={() => { reset.mutate(resetting); setResetting(null) }}>
          <p>임시 비밀번호가 발급되고, 로그인하면 바로 새 비밀번호로 바꿔야 합니다. 잠겨 있던 계정도 풀립니다.</p>
        </ConfirmDialog>
      )}
      {issued && <IssuedPassword {...issued} onClose={() => setIssued(null)} />}
    </div>
  )
}

function IssuedPassword({ username, password, onClose }: { username: string; password: string; onClose: () => void }) {
  useEscape(onClose)
  const [copied, setCopied] = useState(false)
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" role="dialog" aria-modal="true" aria-labelledby="issued-title">
      <div className="card w-[420px] max-w-full shadow-xl p-4 space-y-3">
        <h2 id="issued-title" className="font-medium">임시 비밀번호 — {username}</h2>
        <p className="font-mono text-lg bg-surface-sunken rounded px-3 py-2 select-all break-all">{password}</p>
        <p className="text-sm text-ink-muted">이 창을 닫으면 다시 볼 수 없습니다. 본인에게 직접 전달하고, 메신저 기록에 남기지 마십시오.
          첫 로그인 때 새 비밀번호로 바꾸게 됩니다.</p>
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={() => { navigator.clipboard?.writeText(password).then(() => setCopied(true)).catch(() => undefined) }}>
            {copied ? '복사됨' : '복사'}
          </button>
          <button className="btn btn-primary" onClick={onClose}>전달했습니다</button>
        </div>
      </div>
    </div>
  )
}

function UserDialog({ user, isMe, onClose, onSaved }: {
  user: AdminUser | null; isMe: boolean; onClose: () => void
  onSaved: (issued: { username: string; password: string } | null) => void
}) {
  useEscape(onClose)
  const [form, setForm] = useState({
    username: user?.username ?? '', display_name: user?.display_name ?? '', role_code: user?.role_code ?? 'ANALYST',
    team: user?.team ?? '', email: user?.email ?? '', phone: user?.phone ?? '',
  })
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const save = useMutation({
    mutationFn: async () => {
      if (user) {
        await adminApi.updateUser(user.id, {
          display_name: form.display_name.trim(), team: form.team.trim() || null, email: form.email.trim() || null,
          phone: form.phone.trim() || null, ...(isMe ? {} : { role_code: form.role_code }),
        })
        return null
      }
      let password = tempPassword()
      const account = form.username.trim().toLowerCase()
      while (account.length >= 3 && password.toLowerCase().includes(account)) password = tempPassword()  // 정책: 계정명 포함 금지
      await adminApi.createUser({ username: form.username.trim(), display_name: form.display_name.trim(),
        password, role_code: form.role_code, team: form.team.trim() || null, must_change_password: true })
      return { username: form.username.trim(), password }
    },
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.'),
  })

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/30 p-4" role="dialog" aria-modal="true" aria-labelledby="user-dialog-title">
      <form className="card w-[460px] max-w-full shadow-xl p-4 space-y-2.5" onSubmit={(e) => { e.preventDefault(); setError(null); save.mutate() }}>
        <div className="flex items-center">
          <h2 id="user-dialog-title" className="font-medium flex-1">{user ? '사용자 수정' : '사용자 등록'}</h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-0.5"><span className="text-sm text-ink-muted">계정 *</span>
            <input className="input w-full font-mono" value={form.username} disabled={!!user} required pattern="[A-Za-z0-9._\-]{3,64}"
                   title="영문 · 숫자 · . _ - 3자 이상" onChange={(e) => set('username', e.target.value)} /></label>
          <label className="space-y-0.5"><span className="text-sm text-ink-muted">이름 *</span>
            <input className="input w-full" value={form.display_name} required onChange={(e) => set('display_name', e.target.value)} /></label>
          <label className="space-y-0.5"><span className="text-sm text-ink-muted">역할</span>
            <select className="input w-full" value={form.role_code} disabled={isMe} onChange={(e) => set('role_code', e.target.value)}>
              {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <label className="space-y-0.5"><span className="text-sm text-ink-muted">팀 · 조</span>
            <input className="input w-full" value={form.team} onChange={(e) => set('team', e.target.value)} /></label>
          {user && <>
            <label className="space-y-0.5"><span className="text-sm text-ink-muted">메일</span>
              <input className="input w-full" type="email" value={form.email} onChange={(e) => set('email', e.target.value)} /></label>
            <label className="space-y-0.5"><span className="text-sm text-ink-muted">연락처</span>
              <input className="input w-full" value={form.phone} onChange={(e) => set('phone', e.target.value)} /></label>
          </>}
        </div>
        {isMe && <p className="text-xs text-ink-faint">자기 역할은 바꿀 수 없습니다(관리자가 스스로 권한을 잃지 않게).</p>}
        {!user && <p className="text-xs text-ink-muted">등록하면 임시 비밀번호가 한 번 표시됩니다. 첫 로그인 때 새 비밀번호로 바꾸게 됩니다.</p>}
        {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>취소</button>
          <button className="btn btn-primary" disabled={save.isPending}>{user ? '저장' : '등록'}</button>
        </div>
      </form>
    </div>
  )
}
