/**
 * 교대 마감 점검 — 근무를 넘기기 전에 볼 다섯 줄.
 *
 * 숫자는 서버가 **그 목록과 같은 조건**으로 세어 준다. 그래서 누르면 바로 그것이 열리고,
 * '점검은 3건인데 목록은 2건'이 생기지 않는다. 0 이면 회색, 있으면 색이 붙는다.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { shiftApi, type ClosingRow } from '@/services/api/shift'

const TONE: Record<ClosingRow['tone'], string> = {
  ok: 'text-ink-faint',
  check: 'text-state-check',
  urgent: 'text-state-urgent',
}

export default function ClosingCheck() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['closing-check'], queryFn: shiftApi.closingCheck,
    staleTime: 20_000, refetchInterval: 60_000,
  })

  return (
    <section className="card min-w-0 p-4" aria-label="교대 마감 점검">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">교대 마감 점검</h2>
        {data?.all_clear && (
          <span className="inline-flex items-center gap-1 text-sm text-state-done">
            <CheckCircle2 size={14} /> 넘길 준비가 되었습니다
          </span>
        )}
      </div>

      {isPending && <p className="mt-3 text-ink-muted">불러오는 중…</p>}
      {isError && (
        <p className="mt-3 text-sm">
          마감 점검을 불러오지 못했습니다.{' '}
          <button className="text-brand hover:underline" onClick={() => refetch()}>다시 시도</button>
        </p>
      )}

      {data && (
        <ul className="mt-2 divide-y divide-surface-border">
            {data.rows.map((row) => (
              <li key={row.key}>
                <Link to={row.url} title={row.hint}
                      className="flex items-center gap-2 py-1.5 hover:text-brand">
                  <span className="flex-1 min-w-0">
                    <span className="block font-medium">{row.label}</span>
                    <span className="block text-sm text-ink-faint truncate">{row.hint}</span>
                  </span>
                  <span className={`text-xl font-semibold tabular-nums ${TONE[row.tone]}`}>
                    {row.count.toLocaleString()}
                  </span>
                  <ArrowRight size={13} className="text-ink-faint shrink-0" />
                </Link>
              </li>
            ))}
        </ul>
      )}
    </section>
  )
}
