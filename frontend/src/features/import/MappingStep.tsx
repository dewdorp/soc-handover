/**
 * ② Sheet 분석 + ③ 컬럼 매핑 (UI_STRUCTURE §7).
 *
 * 매핑하지 않은 컬럼도 버리지 않는다 — 원본(raw)에 그대로 남는다는 것을 화면에 밝힌다.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Play } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { importApi, type ImportJob } from '@/services/api/imports'
import { referenceApi } from '@/services/api/reference'

interface Props {
  job: ImportJob
  onStarted: () => void
}

export default function MappingStep({ job, onStarted }: Props) {
  const sheets = job.sheet_summary?.sheets ?? []
  const [selected, setSelected] = useState<Set<string>>(new Set(job.options?.sheets ?? []))
  const [mapping, setMapping] = useState<Record<string, string | null>>(job.column_mapping ?? {})
  const [defaultStatus, setDefaultStatus] = useState(job.options?.default_status ?? 'DONE')
  const [defaultYear, setDefaultYear] = useState<string>(
    job.options?.default_year ? String(job.options.default_year) : '')
  const [error, setError] = useState<string | null>(null)

  const { data: targets } = useQuery({ queryKey: ['import-targets'], queryFn: importApi.targets })
  const { data: statuses } = useQuery({ queryKey: ['statuses'], queryFn: referenceApi.statuses })

  // 선택한 Sheet 에 실제로 있는 헤더만 매핑 대상으로 보여준다.
  const headers = useMemo(() => {
    const out: string[] = []
    for (const s of sheets) {
      if (!selected.has(s.name)) continue
      for (const h of s.headers) if (!out.includes(h)) out.push(h)
    }
    return out
  }, [sheets, selected])

  const sample = (header: string): string => {
    for (const s of sheets) {
      if (!selected.has(s.name)) continue
      for (const row of s.samples) {
        const v = row[header]
        if (v !== null && v !== undefined && v !== '') return String(v)
      }
    }
    return ''
  }

  const start = useMutation({
    mutationFn: async () => {
      const mapped = await importApi.mapping(job.id, {
        sheets: sheets.filter((s) => selected.has(s.name)).map((s) => s.name),
        column_mapping: Object.fromEntries(headers.map((h) => [h, mapping[h] ?? null])),
        default_status: defaultStatus,
        default_year: defaultYear ? Number(defaultYear) : null,
      })
      // Sheet 선택이 그대로면 서버가 STAGED 로 둔다 — 원본을 다시 읽지 않고 해석만 다시 한다.
      return mapped.status === 'STAGED' ? importApi.prepare(job.id) : importApi.stage(job.id)
    },
    onSuccess: () => { setError(null); onStarted() },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '시작하지 못했습니다.'),
  })

  const toggle = (name: string) => {
    const next = new Set(selected)
    next.has(name) ? next.delete(name) : next.add(name)
    setSelected(next)
  }

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4 items-start">
      <section className="card p-3 space-y-2">
        <h2 className="font-medium">② Sheet 분석</h2>
        {(job.sheet_summary?.warnings ?? []).map((w) => (
          <p key={w} className="text-sm text-state-check bg-amber-50 border border-amber-200
                                 rounded px-2 py-1 flex gap-1">
            <AlertTriangle size={13} className="shrink-0 mt-0.5" />{w}
          </p>
        ))}
        <ul className="space-y-1">
          {sheets.map((s) => (
            <li key={s.name}>
              <label className="flex items-start gap-2 cursor-pointer">
                <input type="checkbox" className="mt-1" checked={selected.has(s.name)}
                       onChange={() => toggle(s.name)} />
                <span className="flex-1">
                  <span className="font-medium">{s.name}</span>
                  <span className="text-ink-muted tabular-nums"> · 약 {s.estimated_rows.toLocaleString()}행</span>
                  <br />
                  <span className="text-sm text-ink-faint">
                    {s.header_row ? `헤더 ${s.header_row}행 · 인식 컬럼 ${s.recognized}개` : '빈 Sheet'}
                    {s.year_hint ? ` · 연도 ${s.year_hint}` : ''}
                    {s.recognized < 2 && s.header_row ? ' · 인수인계 표가 아닌 것 같음' : ''}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-3 space-y-3">
        <h2 className="font-medium">③ 컬럼 매핑</h2>
        <table className="w-full text-base">
          <thead className="text-ink-muted">
            <tr className="border-b border-surface-border">
              <th className="text-left font-medium py-1 w-[30%]">Excel 컬럼</th>
              <th className="text-left font-medium py-1 w-[30%]">시스템 필드</th>
              <th className="text-left font-medium py-1">예시 값</th>
            </tr>
          </thead>
          <tbody>
            {headers.map((h) => (
              <tr key={h} className="border-b border-surface-border/60">
                <td className="py-1 pr-2 truncate">{h}</td>
                <td className="py-1 pr-2">
                  <select className="input w-full h-7" value={mapping[h] ?? ''}
                          onChange={(e) => setMapping({ ...mapping, [h]: e.target.value || null })}>
                    <option value="">(원본 보존)</option>
                    {(targets ?? []).map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </td>
                <td className="py-1 text-ink-muted truncate max-w-[280px]" title={sample(h)}>
                  {sample(h) || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-sm text-ink-faint">
          매핑하지 않은 컬럼도 버리지 않습니다. 원본 그대로 보관되어 나중에 확인할 수 있습니다.
        </p>

        <div className="grid grid-cols-2 gap-3 border-t border-surface-border pt-2">
          <label className="space-y-0.5">
            <span className="text-ink-muted">진행상황이 비었거나 모를 때 상태</span>
            <select className="input w-full" value={defaultStatus}
                    onChange={(e) => setDefaultStatus(e.target.value)}>
              {(statuses ?? []).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
            <span className="text-sm text-ink-faint block">
              과거 기록은 대부분 끝난 일이라 기본은 '완료'입니다. 미완료로 두면 오래된 건이
              미완료 목록을 가득 채워 진짜 남은 일이 묻힙니다.
            </span>
          </label>
          <label className="space-y-0.5">
            <span className="text-ink-muted">날짜에 연도가 없을 때 (Sheet 이름에도 없으면)</span>
            <input className="input w-full" inputMode="numeric" placeholder="예: 2025"
                   value={defaultYear} onChange={(e) => setDefaultYear(e.target.value.replace(/\D/g, ''))} />
          </label>
        </div>

        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200
                                     rounded px-2 py-1">{error}</p>
        )}

        <div className="flex justify-end">
          <button className="btn btn-primary" disabled={start.isPending || selected.size === 0}
                  onClick={() => start.mutate()}>
            <Play size={12} /> 검증 실행 (④ 미리보기 · ⑤ 검증 · ⑥ 중복검사)
          </button>
        </div>
      </section>
    </div>
  )
}
