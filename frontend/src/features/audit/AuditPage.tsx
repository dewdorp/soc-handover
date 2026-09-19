/**
 * 감사로그 (FR-I-03) — 기간 · 사용자 · 행위 · 대상 · IP · 결과로 거르고 Excel 로 내보낸다.
 *
 * 기간은 필수(최대 93일, 서버가 검사). ANALYST 는 자기 활동만 보인다(서버가 강제).
 * 행을 누르면 변경 전 · 후를 칸별로 나란히 보여준다 — 감사 때 '무엇이 어떻게 바뀌었나'.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { addDays, format, parseISO } from 'date-fns'
import { Download, Search, X } from 'lucide-react'
import { useCan } from '@/hooks/useAuth'
import { useEscape } from '@/hooks/useHotkeys'
import { adminApi, type AuditQuery, type AuditRow } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'
import { exportApi } from '@/services/api/imports'

const PRESETS = [{ days: 1, label: '오늘' }, { days: 7, label: '7일' }, { days: 30, label: '30일' }, { days: 90, label: '90일' }]
const SIZE = 50
const ROLE_LABEL: Record<string, string> = { ADMIN: '관리자', MANAGER: '근무 관리자', ANALYST: '근무자', SYSTEM: '시스템' }

interface Draft {
  from: string
  to: string
  username: string
  action: string          // '' · 'group:<이름>' · 행위 코드
  resource_type: string
  resource_id: string
  client_ip: string
  result: '' | 'SUCCESS' | 'FAILURE'
}

const today = () => format(new Date(), 'yyyy-MM-dd')
const daysAgo = (n: number) => format(addDays(new Date(), -(n - 1)), 'yyyy-MM-dd')
const empty = (): Draft => ({ from: daysAgo(7), to: today(), username: '', action: '', resource_type: '',
  resource_id: '', client_ip: '', result: '' })

export default function AuditPage() {
  const can = useCan()
  const all = can('audit:read_all')
  const [draft, setDraft] = useState<Draft>(empty)
  const [applied, setApplied] = useState<Draft>(empty)
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<AuditRow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data: catalog } = useQuery({ queryKey: ['audit-catalog'], queryFn: adminApi.auditCatalog, staleTime: 300_000 })

  const query = useMemo<AuditQuery>(() => {
    const group = applied.action.startsWith('group:')
      ? catalog?.groups.find((g) => g.name === applied.action.slice(6))?.actions.map((a) => a.code) : null
    return {
      start: `${applied.from}T00:00:00+09:00`,
      end: `${format(addDays(parseISO(applied.to), 1), 'yyyy-MM-dd')}T00:00:00+09:00`,
      username: applied.username.trim() || undefined,
      actions: group ?? (applied.action ? [applied.action] : undefined),
      resource_type: applied.resource_type || undefined,
      resource_id: applied.resource_id.trim() || undefined,
      client_ip: applied.client_ip.trim() || undefined,
      result: applied.result || null,
      page, size: SIZE,
    }
  }, [applied, page, catalog])

  const { data, isFetching, error: loadError } = useQuery({
    queryKey: ['audit', query], queryFn: () => adminApi.auditSearch(query), placeholderData: keepPreviousData,
  })
  const exporting = useMutation({
    mutationFn: () => adminApi.auditExport({ ...query, page: 1 }),
    onSuccess: (res) => { setError(null); exportApi.download(res.download_token) },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '내보내지 못했습니다.'),
  })

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const apply = (next?: Partial<Draft>) => { const d = { ...draft, ...next }; setDraft(d); setApplied(d); setPage(1) }
  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1
  const shownError = error ?? (loadError instanceof ApiRequestError ? loadError.message : null)

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 flex flex-col min-h-0 p-3 gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <h1 className="text-md font-medium">감사로그</h1>
          <span className="text-sm text-ink-faint">{all ? '누가 언제 무엇을 했는지 — 전체' : '내 활동 기록만 보입니다'}</span>
        </div>

        <form className="flex flex-wrap items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); apply() }}>
          <div className="flex gap-1" role="group" aria-label="기간">
            {PRESETS.map((p) => (
              <button key={p.days} type="button" className={`btn btn-sm ${draft.from === daysAgo(p.days) && draft.to === today() ? 'btn-primary' : ''}`}
                      onClick={() => apply({ from: daysAgo(p.days), to: today() })}>{p.label}</button>
            ))}
          </div>
          <input type="date" className="input" value={draft.from} max={draft.to} aria-label="시작일" onChange={(e) => set('from', e.target.value)} />
          <span className="text-ink-faint">~</span>
          <input type="date" className="input" value={draft.to} min={draft.from} aria-label="끝나는 날" onChange={(e) => set('to', e.target.value)} />
          {all && <input className="input w-28" placeholder="사용자 계정" value={draft.username} aria-label="사용자" onChange={(e) => set('username', e.target.value)} />}
          <select className="input" value={draft.action} aria-label="행위" onChange={(e) => set('action', e.target.value)}>
            <option value="">행위 전체</option>
            {catalog?.groups.map((g) => (
              <optgroup key={g.name} label={g.name}>
                <option value={`group:${g.name}`}>{g.name} 전체</option>
                {g.actions.map((a) => <option key={a.code} value={a.code}>{a.label}</option>)}
              </optgroup>
            ))}
          </select>
          <select className="input" value={draft.resource_type} aria-label="대상 종류" onChange={(e) => set('resource_type', e.target.value)}>
            <option value="">대상 전체</option>
            {catalog?.resource_types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input className="input w-20" placeholder="대상 번호" value={draft.resource_id} aria-label="대상 번호" onChange={(e) => set('resource_id', e.target.value)} />
          <input className="input w-28" placeholder="IP" value={draft.client_ip} aria-label="IP" onChange={(e) => set('client_ip', e.target.value)} />
          <select className="input" value={draft.result} aria-label="결과" onChange={(e) => set('result', e.target.value as Draft['result'])}>
            <option value="">결과 전체</option>
            <option value="SUCCESS">성공</option>
            <option value="FAILURE">실패</option>
          </select>
          <button className="btn btn-sm btn-primary"><Search size={12} /> 검색</button>
          <button type="button" className="btn btn-sm" onClick={() => { const d = empty(); setDraft(d); setApplied(d); setPage(1) }}>초기화</button>
          <span className="flex-1" />
          <button type="button" className="btn btn-sm" disabled={exporting.isPending || !data?.total} onClick={() => exporting.mutate()}>
            <Download size={12} /> Excel
          </button>
        </form>

        {shownError && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{shownError}</p>}

        <div className={`flex-1 min-h-0 overflow-auto border border-surface-border rounded bg-surface ${isFetching ? 'opacity-70' : ''}`}>
          <table className="w-full text-base whitespace-nowrap">
            <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
              <tr>
                {['시각', '사용자', '역할', '행위', '대상', '결과', 'IP'].map((h) => <th key={h} className="text-left font-medium px-2 py-1">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {data?.items.length === 0 && <tr><td colSpan={7} className="py-6 text-center text-ink-faint">조건에 맞는 기록이 없습니다.</td></tr>}
              {data?.items.map((r) => (
                <tr key={r.id} onClick={() => setOpen(r)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setOpen(r) }}
                    className={`border-t border-surface-border/60 cursor-pointer hover:bg-surface-sunken ${open?.id === r.id ? 'bg-brand-soft' : ''}`}>
                  <td className="px-2 py-1 tabular-nums text-ink-muted">{format(parseISO(r.occurred_at), 'yyyy-MM-dd HH:mm:ss')}</td>
                  <td className="px-2 py-1">{r.username ?? '-'}</td>
                  <td className="px-2 py-1 text-ink-muted">{ROLE_LABEL[r.role_code ?? ''] ?? r.role_code ?? '-'}</td>
                  <td className="px-2 py-1">{r.action_label}</td>
                  <td className="px-2 py-1 text-ink-muted">{r.resource_type ? `${r.resource_type}${r.resource_id ? ` #${r.resource_id}` : ''}` : '-'}</td>
                  <td className={`px-2 py-1 ${r.result === 'FAILURE' ? 'text-state-urgent font-medium' : 'text-state-done'}`}>
                    {r.result === 'FAILURE' ? '✖ 실패' : '✔ 성공'}
                  </td>
                  <td className="px-2 py-1 tabular-nums text-ink-muted">{r.client_ip ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-end gap-2 text-sm">
          <span className="text-ink-faint tabular-nums">{data ? `${data.total.toLocaleString()}건` : ''}</span>
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</button>
          <span className="tabular-nums">{page} / {pages}</span>
          <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>다음</button>
        </div>
      </div>
      {open && <AuditDetail row={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value || '(빈 값)'
  return JSON.stringify(value)
}

function AuditDetail({ row, onClose }: { row: AuditRow; onClose: () => void }) {
  useEscape(onClose)
  const before = (row.before_value ?? {}) as Record<string, unknown>
  const after = (row.after_value ?? {}) as Record<string, unknown>
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  return (
    <aside className="w-full lg:w-[480px] max-lg:fixed max-lg:inset-x-0 max-lg:top-12 max-lg:bottom-0 max-lg:z-30 max-lg:shadow-xl shrink-0 border-l border-surface-border bg-surface flex flex-col min-h-0"
           aria-label="감사 기록 상세">
      <div className="px-3 py-2 border-b border-surface-border flex items-center gap-2">
        <span className="font-medium">{row.action_label}</span>
        <span className={`chip h-5 ${row.result === 'FAILURE' ? 'text-state-urgent' : 'text-state-done'}`}>{row.result === 'FAILURE' ? '실패' : '성공'}</span>
        <span className="flex-1" />
        <button onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
      </div>
      <div className="flex-1 overflow-auto p-3 space-y-3 text-sm">
        <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1">
          <dt className="text-ink-muted">시각</dt><dd className="tabular-nums">{format(parseISO(row.occurred_at), 'yyyy-MM-dd HH:mm:ss')}</dd>
          <dt className="text-ink-muted">사용자</dt><dd>{row.username ?? '-'} ({ROLE_LABEL[row.role_code ?? ''] ?? row.role_code ?? '-'})</dd>
          <dt className="text-ink-muted">행위 코드</dt><dd className="font-mono text-xs">{row.action}</dd>
          <dt className="text-ink-muted">대상</dt><dd>{row.resource_type ?? '-'} {row.resource_id ? `#${row.resource_id}` : ''}</dd>
          <dt className="text-ink-muted">IP</dt><dd className="tabular-nums">{row.client_ip ?? '-'}</dd>
          <dt className="text-ink-muted">요청 ID</dt><dd className="font-mono text-xs break-all">{row.request_id ?? '-'}</dd>
          <dt className="text-ink-muted">브라우저</dt><dd className="text-xs text-ink-muted break-all">{row.user_agent ?? '-'}</dd>
          {row.error_message && <><dt className="text-ink-muted">오류</dt><dd className="text-state-urgent">{row.error_message}</dd></>}
        </dl>
        {keys.length > 0 && (
          <section>
            <h3 className="text-ink-muted mb-1">변경 전 · 후</h3>
            <table className="w-full border border-surface-border rounded text-xs">
              <thead className="bg-surface-sunken text-ink-muted"><tr><th className="text-left px-2 py-1 w-28">칸</th><th className="text-left px-2 py-1">전</th><th className="text-left px-2 py-1">후</th></tr></thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k} className="border-t border-surface-border/60 align-top">
                    <td className="px-2 py-1 font-mono">{k}</td>
                    <td className="px-2 py-1 break-all text-ink-muted">{show(before[k])}</td>
                    <td className="px-2 py-1 break-all">{show(after[k])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        {row.detail != null && (
          <section>
            <h3 className="text-ink-muted mb-1">상세</h3>
            <pre className="bg-surface-sunken rounded p-2 text-xs whitespace-pre-wrap break-all">{JSON.stringify(row.detail, null, 2)}</pre>
          </section>
        )}
      </div>
    </aside>
  )
}
