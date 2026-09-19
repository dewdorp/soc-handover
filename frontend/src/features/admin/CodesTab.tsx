/** 상태 코드 · 관계사 관리 — 지우지 않고 비활성화한다(과거 기록이 그 값을 가리킨다). */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { adminApi } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'
import type { Company, HandoverStatus, StatusCategory } from '@/types/api'

const CATEGORY: Record<StatusCategory, string> = { OPEN: '미완료', WAITING: '대기', CLOSED: '완료' }

export default function CodesTab() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Statuses />
      <Companies />
    </div>
  )
}

function useSaver<T>(fn: (v: T) => Promise<unknown>, keys: string[]) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: fn,
    onSuccess: () => { setError(null); for (const k of keys) qc.invalidateQueries({ queryKey: [k] }) },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.'),
  })
  return { save: m.mutate, busy: m.isPending, error }
}

function Statuses() {
  const { data } = useQuery({ queryKey: ['admin-statuses'], queryFn: adminApi.statuses })
  const { save, busy, error } = useSaver((s: Omit<HandoverStatus, 'is_system'>) => adminApi.upsertStatus(s), ['admin-statuses', 'statuses'])
  const off = useSaver((code: string) => adminApi.deactivateStatus(code), ['admin-statuses', 'statuses'])
  const [draft, setDraft] = useState({ code: '', name: '', category: 'OPEN' as StatusCategory })

  return (
    <section className="card p-3 space-y-2">
      <h2 className="font-medium">상태 코드</h2>
      <p className="text-xs text-ink-muted">분류가 '완료'인 상태는 미완료 · 지연 · 이어 넘기기에서 빠집니다. 기본 상태는 지울 수 없고 이름 · 순서만 바꿉니다.</p>
      {(error || off.error) && <p role="alert" className="text-sm text-state-urgent">{error ?? off.error}</p>}
      <table className="w-full text-base">
        <thead className="text-ink-muted text-sm"><tr><th className="text-left font-medium">코드</th><th className="text-left font-medium">이름</th><th className="text-left font-medium">분류</th><th className="text-left font-medium w-16">순서</th><th /></tr></thead>
        <tbody>
          {data?.map((s) => (
            <tr key={s.code} className={`border-t border-surface-border/60 ${s.is_active ? '' : 'text-ink-faint'}`}>
              <td className="py-1 font-mono text-sm">{s.code}{s.is_system && <span className="text-xs text-ink-faint"> 기본</span>}</td>
              <td><input className="input h-6 w-28" defaultValue={s.name} aria-label={`${s.code} 이름`}
                         onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== s.name) save({ ...s, name: v }) }} /></td>
              <td>
                <select className="input h-6" value={s.category} disabled={busy} aria-label={`${s.code} 분류`}
                        onChange={(e) => save({ ...s, category: e.target.value as StatusCategory })}>
                  {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </td>
              <td><input className="input h-6 w-14" type="number" defaultValue={s.sort_order} aria-label={`${s.code} 순서`}
                         onBlur={(e) => { const v = Number(e.target.value); if (v !== s.sort_order) save({ ...s, sort_order: v }) }} /></td>
              <td className="text-right">
                {s.is_active
                  ? !s.is_system && <button className="btn btn-sm" disabled={off.busy} onClick={() => off.save(s.code)}>비활성화</button>
                  : <button className="btn btn-sm" disabled={busy} onClick={() => save({ ...s, is_active: true })}>다시 사용</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="flex flex-wrap gap-1 items-center" onSubmit={(e) => {
        e.preventDefault()
        save({ code: draft.code.trim().toUpperCase(), name: draft.name.trim(), category: draft.category,
               color: null, icon: null, sort_order: 100, is_active: true })
        setDraft({ code: '', name: '', category: 'OPEN' })
      }}>
        <input className="input w-24 font-mono uppercase" placeholder="CODE" value={draft.code} required pattern="[A-Za-z0-9_]+"
               onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))} aria-label="새 상태 코드" />
        <input className="input w-28" placeholder="이름" value={draft.name} required
               onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} aria-label="새 상태 이름" />
        <select className="input" value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value as StatusCategory }))} aria-label="새 상태 분류">
          {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button className="btn btn-sm" disabled={busy}><Plus size={12} /> 추가</button>
      </form>
    </section>
  )
}

function Companies() {
  const { data } = useQuery({ queryKey: ['admin-companies'], queryFn: adminApi.companies })
  const upd = useSaver(({ id, ...body }: Partial<Company> & { id: number }) => adminApi.updateCompany(id, body), ['admin-companies', 'companies'])
  const add = useSaver((body: { name: string; short_name?: string | null }) => adminApi.createCompany(body), ['admin-companies', 'companies'])
  const [draft, setDraft] = useState({ name: '', short_name: '' })

  return (
    <section className="card p-3 space-y-2">
      <h2 className="font-medium">관계사</h2>
      <p className="text-xs text-ink-muted">Excel Import 에서 이름이 조금 달라도 같은 관계사로 묶으려면 Import 화면의 값 매핑을 쓰십시오. 비활성 관계사는 새 인수인계에서 고를 수 없습니다.</p>
      {(upd.error || add.error) && <p role="alert" className="text-sm text-state-urgent">{upd.error ?? add.error}</p>}
      <table className="w-full text-base">
        <thead className="text-ink-muted text-sm"><tr><th className="text-left font-medium">이름</th><th className="text-left font-medium">약칭</th><th className="text-left font-medium w-16">순서</th><th /></tr></thead>
        <tbody>
          {data?.map((c) => (
            <tr key={c.id} className={`border-t border-surface-border/60 ${c.is_active ? '' : 'text-ink-faint'}`}>
              <td className="py-1"><input className="input h-6 w-36" defaultValue={c.name} aria-label={`${c.name} 이름`}
                                          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== c.name) upd.save({ id: c.id, name: v }) }} /></td>
              <td><input className="input h-6 w-20" defaultValue={c.short_name ?? ''} aria-label={`${c.name} 약칭`}
                         onBlur={(e) => { const v = e.target.value.trim() || null; if (v !== c.short_name) upd.save({ id: c.id, short_name: v }) }} /></td>
              <td><input className="input h-6 w-14" type="number" defaultValue={c.sort_order} aria-label={`${c.name} 순서`}
                         onBlur={(e) => { const v = Number(e.target.value); if (v !== c.sort_order) upd.save({ id: c.id, sort_order: v }) }} /></td>
              <td className="text-right">
                <button className="btn btn-sm" disabled={upd.busy} onClick={() => upd.save({ id: c.id, is_active: !c.is_active })}>
                  {c.is_active ? '비활성화' : '다시 사용'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="flex flex-wrap gap-1 items-center" onSubmit={(e) => {
        e.preventDefault()
        add.save({ name: draft.name.trim(), short_name: draft.short_name.trim() || null })
        setDraft({ name: '', short_name: '' })
      }}>
        <input className="input w-40" placeholder="관계사 이름" value={draft.name} required
               onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} aria-label="새 관계사 이름" />
        <input className="input w-24" placeholder="약칭" value={draft.short_name}
               onChange={(e) => setDraft((d) => ({ ...d, short_name: e.target.value }))} aria-label="새 관계사 약칭" />
        <button className="btn btn-sm" disabled={add.busy}><Plus size={12} /> 추가</button>
      </form>
    </section>
  )
}
