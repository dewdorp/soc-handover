/**
 * ④ 미리보기 · ⑤ 검증 · ⑥ 중복검사 결과를 검토하고 무엇을 가져올지 고른다.
 *
 * 중복 의심은 기본 제외, 오류는 가져올 수 없음. 둘 다 **지우지 않는다** — 목록에 남아
 * 사람이 확인하고 필요하면 '가져오기'로 바꿀 수 있다(§48).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Upload } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { ApiRequestError } from '@/services/api/client'
import { importApi, type ImportJob, type ImportRow, type RowKind } from '@/services/api/imports'
import { referenceApi } from '@/services/api/reference'

const TABS: { kind: RowKind; label: string }[] = [
  { kind: 'import', label: '가져올 행' },
  { kind: 'duplicate', label: '중복 의심' },
  { kind: 'warning', label: '경고' },
  { kind: 'error', label: '오류' },
  { kind: 'skip', label: '제외' },
  { kind: 'all', label: '전체' },
]

const CREATE = '__CREATE__'

interface Props {
  job: ImportJob
  onWorkStarted: () => void
  /** 결과를 보고 매핑이 잘못된 걸 알았을 때 되돌아간다. 원본은 다시 읽지 않는다. */
  onRemap: () => void
}

export default function ReviewStep({ job, onWorkStarted, onRemap }: Props) {
  const qc = useQueryClient()
  const [tab, setTab] = useState<RowKind>('import')
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const { data: report } = useQuery({
    queryKey: ['import-report', job.id, job.status], queryFn: () => importApi.report(job.id),
  })
  const { data: rows } = useQuery({
    queryKey: ['import-rows', job.id, tab, page, job.status],
    queryFn: () => importApi.rows(job.id, tab, page),
    enabled: tab !== 'error',
  })
  const { data: errors } = useQuery({
    queryKey: ['import-errors', job.id, page, job.status],
    queryFn: () => importApi.errors(job.id, page),
    enabled: tab === 'error',
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['import-report', job.id] })
    qc.invalidateQueries({ queryKey: ['import-rows', job.id] })
  }

  const decide = useMutation({
    mutationFn: ({ ids, decision }: { ids: number[]; decision: 'IMPORT' | 'SKIP' | 'PENDING' }) =>
      importApi.decisions(job.id, ids, decision),
    onSuccess: refresh,
  })

  const commit = useMutation({
    mutationFn: () => importApi.commit(job.id),
    onSuccess: () => { setError(null); onWorkStarted() },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '가져오지 못했습니다.'),
  })

  const willImport = report?.will_import ?? 0

  // 행 목록에 DONE·IN_PROGRESS 같은 내부 코드를 그대로 보이지 않게 이름으로 바꾼다.
  const { data: statuses } = useQuery({ queryKey: ['statuses'], queryFn: referenceApi.statuses })
  const statusName = (code: unknown) =>
    statuses?.find((s) => s.code === code)?.name ?? String(code ?? '-')

  return (
    <div className="space-y-3">
      <section className="card p-3">
        <div className="flex flex-wrap gap-x-5 gap-y-1 items-baseline">
          <Stat label="적재" value={report?.total} />
          <Stat label="정상" value={report?.valid} />
          <Stat label="경고" value={report?.warning} tone="check" />
          <Stat label="오류" value={report?.error} tone="urgent" />
          <Stat label="중복 의심" value={report?.duplicate}
                hint={`기존 ${report?.duplicate_existing ?? 0} · 파일 안 ${report?.duplicate_batch ?? 0}`} />
          <Stat label="빈 행" value={report?.blank} />
          <span className="flex-1" />
          <Stat label="가져올 행" value={willImport} tone="brand" />
        </div>
      </section>

      <ValueMapping job={job} onApplied={onWorkStarted} />

      <section className="card">
        <nav className="flex items-center gap-1 px-2 pt-2 border-b border-surface-border" role="tablist">
          {TABS.map((t) => (
            <button key={t.kind} role="tab" aria-selected={tab === t.kind}
                    onClick={() => { setTab(t.kind); setPage(1) }}
                    className={`px-2 h-7 border-b-2 ${tab === t.kind
                      ? 'border-brand text-brand font-medium' : 'border-transparent text-ink-muted'}`}>
              {t.label}
            </button>
          ))}
          <span className="flex-1" />
          {(report?.error ?? 0) > 0 && (
            <button className="btn btn-sm mb-1" onClick={() => importApi.downloadErrors(job.id)}>
              <Download size={11} /> 실패행 Excel
            </button>
          )}
        </nav>

        {tab === 'error' ? (
          <table className="w-full text-base">
            <thead className="text-ink-muted bg-surface-sunken">
              <tr>
                <th className="text-left font-medium px-2 py-1">Sheet</th>
                <th className="text-left font-medium px-2 py-1">행</th>
                <th className="text-left font-medium px-2 py-1">오류</th>
                <th className="text-left font-medium px-2 py-1">값</th>
              </tr>
            </thead>
            <tbody>
              {(errors?.items ?? []).map((e) => (
                <tr key={e.id} className="border-t border-surface-border/60">
                  <td className="px-2 py-1">{e.sheet_name}</td>
                  <td className="px-2 py-1 tabular-nums">{e.source_row}</td>
                  <td className="px-2 py-1 text-state-urgent">{e.message}</td>
                  <td className="px-2 py-1 text-ink-muted truncate max-w-[240px]">{e.raw_value ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <RowTable rows={rows?.items ?? []} statusName={statusName}
                    onDecide={(ids, decision) => decide.mutate({ ids, decision })} />
        )}

        <Pager page={page} total={(tab === 'error' ? errors?.total : rows?.total) ?? 0}
               onPage={setPage} />
      </section>

      {error && (
        <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200
                                   rounded px-2 py-1">{error}</p>
      )}

      <div className="flex justify-between">
        <button className="btn" onClick={onRemap}>← 컬럼 매핑 다시</button>
        <button className="btn btn-primary" disabled={commit.isPending || willImport === 0}
                onClick={() => setConfirming(true)}>
          <Upload size={12} /> ⑦ {willImport.toLocaleString()}건 가져오기
        </button>
        {confirming && (
          <ConfirmDialog title={`${willImport.toLocaleString()}건을 인수인계로 가져옵니다`}
                         confirmLabel="가져오기" busy={commit.isPending}
                         onCancel={() => setConfirming(false)}
                         onConfirm={() => { setConfirming(false); commit.mutate() }}>
            <p>가져온 뒤에도 관리자는 작업 단위로 되돌릴 수 있습니다.</p>
          </ConfirmDialog>
        )}
      </div>
    </div>
  )
}

function ValueMapping({ job, onApplied }: { job: ImportJob; onApplied: () => void }) {
  const { data: companyStats } = useQuery({
    queryKey: ['import-values', job.id, 'company', job.status],
    queryFn: () => importApi.values(job.id, 'company'),
  })
  const { data: statusStats } = useQuery({
    queryKey: ['import-values', job.id, 'status', job.status],
    queryFn: () => importApi.values(job.id, 'status'),
  })
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: referenceApi.companies })
  const { data: statuses } = useQuery({ queryKey: ['statuses'], queryFn: referenceApi.statuses })

  const [companyDraft, setCompanyDraft] = useState<Record<string, string>>({})
  const [statusDraft, setStatusDraft] = useState<Record<string, string>>({})

  const unmatchedCompanies = useMemo(() => (companyStats ?? []).filter((v) => !v.matched), [companyStats])
  const unmatchedStatuses = useMemo(() => (statusStats ?? []).filter((v) => !v.matched), [statusStats])

  const apply = useMutation({
    mutationFn: async () => {
      const company = Object.fromEntries(Object.entries(companyDraft)
        .filter(([, v]) => v).map(([k, v]) => [k, v === CREATE ? CREATE : Number(v)]))
      const status = Object.fromEntries(Object.entries(statusDraft).filter(([, v]) => v))
      // 두 번째 요청은 첫 번째 재검증이 끝난 뒤여야 한다(작업 점유 충돌 방지).
      if (Object.keys(company).length) await importApi.valueMap(job.id, 'company', company)
      if (Object.keys(status).length) {
        if (Object.keys(company).length) await waitIdle(job.id)
        await importApi.valueMap(job.id, 'status', status)
      }
    },
    onSuccess: () => { setCompanyDraft({}); setStatusDraft({}); onApplied() },
  })

  if (!unmatchedCompanies.length && !unmatchedStatuses.length) return null
  const dirty = Object.values(companyDraft).some(Boolean) || Object.values(statusDraft).some(Boolean)

  return (
    <section className="card p-3 space-y-2">
      <h2 className="font-medium">값 매핑 필요</h2>
      <div className="grid grid-cols-2 gap-4">
        {unmatchedCompanies.length > 0 && (
          <div className="space-y-1">
            <h3 className="text-ink-muted">등록되지 않은 관계사</h3>
            {unmatchedCompanies.map((v) => (
              <div key={v.value} className="flex items-center gap-2">
                <span className="w-40 truncate" title={v.variants.join(' · ')}>
                  {v.value}
                  {v.variants.length > 1 && (
                    <span className="text-ink-faint text-sm"> 외 표기 {v.variants.length - 1}</span>
                  )}
                </span>
                <span className="text-ink-faint tabular-nums w-12">{v.count}건</span>
                <select className="input flex-1 h-7" value={companyDraft[v.value] ?? ''}
                        onChange={(e) => setCompanyDraft({ ...companyDraft, [v.value]: e.target.value })}>
                  <option value="">'미지정'으로 (원래 이름은 비고에 남김)</option>
                  <option value={CREATE}>새 관계사로 등록</option>
                  {(companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            ))}
          </div>
        )}
        {unmatchedStatuses.length > 0 && (
          <div className="space-y-1">
            <h3 className="text-ink-muted">알 수 없는 진행상황</h3>
            {unmatchedStatuses.map((v) => (
              <div key={v.value} className="flex items-center gap-2">
                <span className="w-32 truncate" title={v.value}>{v.value}</span>
                <span className="text-ink-faint tabular-nums w-12">{v.count}건</span>
                <select className="input flex-1 h-7" value={statusDraft[v.value] ?? ''}
                        onChange={(e) => setStatusDraft({ ...statusDraft, [v.value]: e.target.value })}>
                  <option value="">기본 상태로</option>
                  {(statuses ?? []).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                </select>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex justify-end">
        <button className="btn" disabled={!dirty || apply.isPending} onClick={() => apply.mutate()}>
          값 매핑 적용 후 다시 검증
        </button>
      </div>
    </section>
  )
}

async function waitIdle(jobId: number): Promise<void> {
  for (let i = 0; i < 120; i++) {
    const job = await importApi.get(jobId)
    if (job.status !== 'RUNNING') return
    await new Promise((r) => setTimeout(r, 500))
  }
}

function RowTable({ rows, statusName, onDecide }: {
  rows: ImportRow[]
  statusName: (code: unknown) => string
  onDecide: (ids: number[], decision: 'IMPORT' | 'SKIP' | 'PENDING') => void
}) {
  return (
    <table className="w-full text-base">
      <thead className="text-ink-muted bg-surface-sunken">
        <tr>
          <th className="px-2 py-1 w-14 font-medium">가져오기</th>
          <th className="text-left font-medium px-2 py-1">Sheet·행</th>
          <th className="text-left font-medium px-2 py-1">관계사</th>
          <th className="text-left font-medium px-2 py-1">등록일</th>
          <th className="text-left font-medium px-2 py-1">상태</th>
          <th className="text-left font-medium px-2 py-1">제목</th>
          <th className="text-left font-medium px-2 py-1">전달자</th>
          <th className="text-left font-medium px-2 py-1">알림</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={8} className="px-2 py-4 text-center text-ink-faint">해당하는 행이 없습니다.</td></tr>
        )}
        {rows.map((r) => {
          const n = r.normalized ?? {}
          const blocked = r.status === 'ERROR' || r.status === 'IMPORTED'
          return (
            <tr key={r.id} className="border-t border-surface-border/60 align-top">
              <td className="px-2 py-1 text-center">
                <input type="checkbox" checked={r.will_import || r.status === 'IMPORTED'}
                       disabled={blocked}
                       aria-label={`${r.sheet_name} ${r.source_row}행 가져오기`}
                       onChange={(e) => onDecide([r.id], e.target.checked ? 'IMPORT' : 'SKIP')} />
              </td>
              <td className="px-2 py-1 tabular-nums whitespace-nowrap">{r.sheet_name} · {r.source_row}</td>
              <td className="px-2 py-1">{String(n.company_name ?? '-')}</td>
              <td className="px-2 py-1 tabular-nums">{String(n.registered_date ?? '-')}</td>
              <td className="px-2 py-1">{statusName(n.status_code)}</td>
              <td className="px-2 py-1 truncate max-w-[280px]" title={String(n.content ?? '')}>
                {String(n.title ?? '-')}
              </td>
              <td className="px-2 py-1">{String(n.sender_name_raw ?? '-')}</td>
              <td className="px-2 py-1 text-sm">
                {r.dup_type === 'EXISTING' && (
                  <span className="text-state-check block">
                    이미 있음{r.dup_handover_id ? ` (#${r.dup_handover_id})` : ''}
                  </span>
                )}
                {r.dup_type === 'BATCH' && <span className="text-state-check block">파일 안에서 반복</span>}
                {(r.warnings ?? []).map((w) => (
                  <span key={w.code} className="text-ink-muted block">{w.message}</span>
                ))}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Stat({ label, value, hint, tone }: {
  label: string; value?: number; hint?: string; tone?: 'urgent' | 'check' | 'brand'
}) {
  const color = tone === 'urgent' ? 'text-state-urgent' : tone === 'check' ? 'text-state-check'
    : tone === 'brand' ? 'text-brand' : 'text-ink'
  return (
    <span title={hint}>
      <span className="text-ink-muted">{label} </span>
      <b className={`tabular-nums ${color}`}>{(value ?? 0).toLocaleString()}</b>
    </span>
  )
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (p: number) => void }) {
  const last = Math.max(1, Math.ceil(total / 50))
  if (last <= 1) return null
  return (
    <div className="flex items-center justify-end gap-2 px-2 py-1 border-t border-surface-border">
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>이전</button>
      <span className="tabular-nums text-ink-muted">{page} / {last}</span>
      <button className="btn btn-sm" disabled={page >= last} onClick={() => onPage(page + 1)}>다음</button>
    </div>
  )
}
