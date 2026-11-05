/**
 * 비밀번호 보관 (FR-V) — 관계사 장비의 접속 계정과 비밀번호를 한 곳에 둔다.
 *
 * 화면에는 비밀번호가 **절대 그대로 나오지 않는다**. '보기'를 눌러 본인 계정 비밀번호를
 * 다시 확인해야 한 번 보이고, 그 기록은 감사로그에 남는다.
 * 공용(교대 근무자 전원)과 개인(나만) 두 가지가 한 목록에 섞여 있고 칩으로 구분한다.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { Eye, KeyRound, Lock, Plus, Search, Users } from 'lucide-react'
import CredentialDialog from '@/features/credentials/CredentialDialog'
import RevealDialog from '@/features/credentials/RevealDialog'
import { credentialApi, type Credential, type CredentialScope } from '@/services/api/credentials'

const SCOPES: { key: CredentialScope | ''; label: string }[] = [
  { key: '', label: '전체' },
  { key: 'SHARED', label: '공용' },
  { key: 'PERSONAL', label: '개인' },
]

export default function CredentialsPage() {
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const [scope, setScope] = useState<CredentialScope | ''>('')
  const [revealing, setRevealing] = useState<Credential | null>(null)
  const [editing, setEditing] = useState<Credential | null>(null)
  const [creating, setCreating] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['credentials', applied, scope],
    queryFn: () => credentialApi.list({ q: applied, scope }),
  })

  return (
    <div className="p-3 sm:p-4 space-y-3 min-h-0 flex flex-col">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <KeyRound size={17} className="box-content rounded-md bg-brand-soft p-1.5 text-brand" /> 비밀번호
        </h1>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          <Plus size={13} /> 등록
        </button>
      </div>
      <div className="card flex flex-wrap items-center gap-3 p-3">
        <div className="relative flex-1 min-w-[12rem] max-w-xl">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input className="input w-full h-8 pl-7" placeholder="장비명 · 계정 · 접속 방법으로 찾기"
                 value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') setApplied(q.trim()) }} />
        </div>
        <div className="flex gap-1">
          {SCOPES.map((s) => (
            <button key={s.key || 'all'}
                    className={`btn btn-sm ${scope === s.key ? 'btn-primary' : ''}`}
                    onClick={() => setScope(s.key)}>{s.label}</button>
          ))}
        </div>
      </div>

      <p className="border-l-2 border-brand/40 pl-3 text-sm text-ink-muted">
        비밀번호는 서버에 암호로 바꿔서 보관합니다. 여는 기록은 누가 · 언제 · 어느 장비인지 감사로그에 남습니다.
      </p>

      <div className="card flex-1 overflow-auto">
        <table className="w-full text-base">
          <thead className="bg-surface-sunken text-ink-muted whitespace-nowrap">
            <tr>
              <th className="text-left font-semibold px-3 py-2">관계사</th>
              <th className="text-left font-semibold px-3 py-2">장비명</th>
              <th className="text-left font-semibold px-3 py-2">접속 방법</th>
              <th className="text-left font-semibold px-3 py-2">계정</th>
              <th className="text-left font-semibold px-3 py-2">범위</th>
              <th className="text-left font-semibold px-3 py-2">마지막 변경</th>
              <th className="px-3 py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={7} className="py-8 text-center text-ink-faint">불러오는 중…</td></tr>
            )}
            {!isLoading && (data ?? []).length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-ink-faint">
                {applied ? '찾는 항목이 없습니다.' : '등록된 비밀번호가 없습니다.'}
              </td></tr>
            )}
            {(data ?? []).map((row) => (
              <tr key={row.id} className="border-t border-surface-border/60 hover:bg-surface-sunken">
                <td className="px-3 py-1.5">{row.company ?? <span className="text-ink-faint">미지정</span>}</td>
                <td className="px-3 py-1.5">
                  <button className="font-medium text-brand hover:underline text-left" onClick={() => setEditing(row)}>
                    {row.device_name}
                  </button>
                  {row.note && <div className="text-xs text-ink-faint truncate max-w-[280px]">{row.note}</div>}
                </td>
                <td className="px-3 py-1.5 text-ink-muted">{row.access_method ?? '-'}</td>
                <td className="px-3 py-1.5 font-mono">{row.username ?? '-'}</td>
                <td className="px-3 py-1.5">
                  {row.scope === 'SHARED'
                    ? <span className="chip gap-1 border-transparent bg-brand-soft font-medium text-brand"><Users size={11} /> 공용</span>
                    : <span className="chip gap-1 border-transparent bg-slate-100 font-medium text-slate-700"><Lock size={11} /> 개인</span>}
                </td>
                <td className="px-3 py-1.5 text-ink-muted whitespace-nowrap tabular-nums">
                  {row.rotated_at ? format(parseISO(row.rotated_at), 'yyyy-MM-dd HH:mm') : '-'}
                  {row.rotated_by && <span className="text-ink-faint"> · {row.rotated_by}</span>}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <button className="btn btn-sm" onClick={() => setRevealing(row)}>
                    <Eye size={12} /> 보기
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {revealing && <RevealDialog credential={revealing} onClose={() => setRevealing(null)} />}
      {(creating || editing) && (
        <CredentialDialog credential={editing}
                          onClose={() => { setCreating(false); setEditing(null) }} />
      )}
    </div>
  )
}
