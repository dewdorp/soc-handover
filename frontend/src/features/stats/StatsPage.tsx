/**
 * 통계 (/stats · MANAGER 이상) — 관계사 · 상태 · 월별 등록 건수, 교대 인계 확인율 · 확인까지 걸린 시간, 지연.
 *
 * 기간은 등록일 기준(최대 366일, 서버가 검사). '지금 지연' · '확인 대기'는 기간과 무관한 현재 값이다.
 * 그래프는 막대마다 마우스를 올리면 값을 보여주고, '표로 보기'로 같은 숫자를 표로 볼 수 있다.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { addDays, addMonths, format, parseISO, startOfMonth, startOfYear } from 'date-fns'
import { useCan } from '@/hooks/useAuth'
import { adminApi, type StatsSummary } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

/** 순서형 두 단계(진행 중 → 완료)와 단일 계열 — 흰 바탕 대비 검증한 값. */
const C_OPEN = '#1c5cab'
const C_DONE = '#86b6ef'
const C_ONE = '#2a78d6'

const iso = (d: Date) => format(d, 'yyyy-MM-dd')
const PRESETS = [
  { key: '7', label: '최근 7일', range: () => [iso(addDays(new Date(), -6)), iso(new Date())] },
  { key: '30', label: '최근 30일', range: () => [iso(addDays(new Date(), -29)), iso(new Date())] },
  { key: '90', label: '최근 90일', range: () => [iso(addDays(new Date(), -89)), iso(new Date())] },
  { key: 'year', label: '올해', range: () => [iso(startOfYear(new Date())), iso(new Date())] },
] as const

function minutesText(m: number | null) {
  if (m == null) return '—'
  if (m < 60) return `${Math.round(m)}분`
  const h = Math.floor(m / 60), r = Math.round(m % 60)
  return r ? `${h}시간 ${r}분` : `${h}시간`
}

export default function StatsPage() {
  const can = useCan()
  const [preset, setPreset] = useState<string>('30')
  const [range, setRange] = useState<string[]>(() => PRESETS[1].range())
  const [draft, setDraft] = useState<string[]>(range)
  const { data, isLoading, error } = useQuery({
    queryKey: ['stats', range[0], range[1]], queryFn: () => adminApi.stats(range[0], range[1]),
    enabled: can('stats:read_all'), placeholderData: keepPreviousData,
  })
  if (!can('stats:read_all')) return <p className="p-4 text-ink-muted">근무 관리자 이상만 볼 수 있는 화면입니다.</p>

  const pick = (key: string) => {
    const p = PRESETS.find((x) => x.key === key)!
    const r = p.range()
    setPreset(key); setRange(r); setDraft(r)
  }

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-6xl p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-md font-medium mr-2">통계</h1>
          <div className="inline-flex rounded border border-surface-border overflow-hidden" role="group" aria-label="기간">
            {PRESETS.map((p) => (
              <button key={p.key} onClick={() => pick(p.key)} aria-pressed={preset === p.key}
                      className={`px-2.5 h-7 text-sm border-r last:border-r-0 border-surface-border ${preset === p.key ? 'bg-brand-soft text-brand font-medium' : 'hover:bg-surface-sunken'}`}>
                {p.label}
              </button>
            ))}
          </div>
          <form className="inline-flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); setPreset('custom'); setRange(draft) }}>
            <input type="date" className="input h-7" value={draft[0]} max={draft[1]} aria-label="시작일"
                   onChange={(e) => setDraft([e.target.value, draft[1]])} />
            <span className="text-ink-faint">~</span>
            <input type="date" className="input h-7" value={draft[1]} min={draft[0]} aria-label="종료일"
                   onChange={(e) => setDraft([draft[0], e.target.value])} />
            <button className="btn btn-sm" disabled={!draft[0] || !draft[1]}>적용</button>
          </form>
        </div>

        {error && <p role="alert" className="text-sm text-state-urgent">{error instanceof ApiRequestError ? error.message : '통계를 불러오지 못했습니다.'}</p>}
        {isLoading || !data ? <p className="text-ink-faint">불러오는 중…</p> : <Body s={data} />}
      </div>
    </div>
  )
}

function Body({ s }: { s: StatsSummary }) {
  return (
    <>
      <section className="grid gap-2 grid-cols-2 md:grid-cols-3 xl:grid-cols-6" aria-label="요약">
        <Tile label="등록 인수인계" value={s.total.toLocaleString()} sub={`${s.start} ~ ${s.end}`} />
        <Tile label="교대 인계 확인율" value={s.ack.rate == null ? '—' : `${s.ack.rate}%`}
              sub={s.ack.items ? `${s.ack.items.toLocaleString()}건 중 ${s.ack.acked.toLocaleString()}건 확인` : '기간 안에 보낸 인계 없음'} />
        <Tile label="확인까지 (중앙값)" value={minutesText(s.ack.median_minutes)}
              sub={s.ack.avg_minutes == null ? '확인된 건 없음' : `평균 ${minutesText(s.ack.avg_minutes)}`} />
        <Tile label="확인 대기 (지금)" value={s.ack.pending_now.toLocaleString()} sub="받았지만 아직 확인 안 한 건" warn={s.ack.pending_now > 0} />
        <Tile label="지연 (지금)" value={`${s.overdue.handovers.toLocaleString()} · ${s.overdue.tasks.toLocaleString()}`}
              sub="인수인계 · 할일 — 날짜 지남, 미완료" warn={s.overdue.handovers + s.overdue.tasks > 0} />
        <Tile label="할일 완료 / 생성" value={`${s.tasks.completed.toLocaleString()} / ${s.tasks.created.toLocaleString()}`}
              sub={s.tasks.median_hours == null ? '완료된 할일 없음' : `완료까지 중앙값 ${s.tasks.median_hours}시간`} />
      </section>

      {s.total === 0 ? (
        <p className="card p-4 text-ink-muted">이 기간에 등록된 인수인계가 없습니다. 기간을 넓혀 보십시오.</p>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          <CompanyChart s={s} />
          <StatusChart s={s} />
          <div className="xl:col-span-2"><MonthChart s={s} /></div>
        </div>
      )}
    </>
  )
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <div className="card px-3 py-2">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${warn ? 'text-state-check' : ''}`}>{value}</p>
      <p className="text-xs text-ink-faint truncate" title={sub}>{sub}</p>
    </div>
  )
}

/** 그래프 틀 — 제목 · 범례 · '표로 보기' 전환. */
function ChartCard({ title, legend, table, children }: { title: string; legend?: ReactNode; table: ReactNode; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false)
  return (
    <section className="card p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-medium">{title}</h2>
        {!asTable && legend}
        <span className="flex-1" />
        <button className="text-sm text-brand hover:underline" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? '그래프로 보기' : '표로 보기'}
        </button>
      </div>
      {asTable ? <div className="overflow-auto max-h-96">{table}</div> : children}
    </section>
  )
}

function Swatch({ color, label }: { color: string; label: string }) {
  return <span className="inline-flex items-center gap-1 text-sm text-ink-muted"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />{label}</span>
}

/** 막대 위 말풍선 — 마우스를 올리거나 키보드로 초점을 주면 보인다. */
function Tip({ lines }: { lines: string[] }) {
  return (
    <div role="tooltip" className="absolute z-10 left-1/2 -translate-x-1/2 bottom-full mb-1 whitespace-nowrap rounded bg-ink text-white text-xs px-2 py-1 shadow pointer-events-none">
      {lines.map((l) => <div key={l}>{l}</div>)}
    </div>
  )
}

function CompanyChart({ s }: { s: StatsSummary }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...s.by_company.map((c) => c.total))
  return (
    <ChartCard title="관계사별"
               legend={<span className="flex gap-3"><Swatch color={C_OPEN} label="진행 중" /><Swatch color={C_DONE} label="완료" /></span>}
               table={<NumTable head={['관계사', '진행 중', '완료', '합계']} rows={s.by_company.map((c) => [c.company, c.open, c.closed, c.total])} />}>
      <ul className="space-y-1.5">
        {s.by_company.map((c, i) => (
          <li key={c.company} className="grid grid-cols-[minmax(4rem,9rem)_1fr] items-center gap-2">
            <span className="text-sm truncate text-right" title={c.company}>{c.company}</span>
            <div className="flex items-center gap-1.5 min-w-0">
              <div className="relative flex gap-[2px] h-[18px] outline-none" style={{ width: `${(c.total / max) * 100}%`, minWidth: 4 }}
                   tabIndex={0} aria-label={`${c.company}: 진행 중 ${c.open}, 완료 ${c.closed}, 합계 ${c.total}`}
                   onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                {c.open > 0 && <div className={`h-full ${c.closed ? '' : 'rounded-r'}`} style={{ flexGrow: c.open, background: C_OPEN }} />}
                {c.closed > 0 && <div className="h-full rounded-r" style={{ flexGrow: c.closed, background: C_DONE }} />}
                {hover === i && <Tip lines={[c.company, `진행 중 ${c.open}건`, `완료 ${c.closed}건`, `합계 ${c.total}건`]} />}
              </div>
              <span className="text-sm tabular-nums text-ink-muted shrink-0">{c.total}</span>
            </div>
          </li>
        ))}
      </ul>
    </ChartCard>
  )
}

function StatusChart({ s }: { s: StatsSummary }) {
  const [hover, setHover] = useState<number | null>(null)
  const rows = s.by_status.filter((r) => r.count > 0)
  const max = Math.max(1, ...rows.map((r) => r.count))
  const CAT: Record<string, string> = { OPEN: '미완료', WAITING: '대기', CLOSED: '완료' }
  return (
    <ChartCard title="상태별"
               table={<NumTable head={['상태', '분류', '건수']} rows={rows.map((r) => [r.name, CAT[r.category] ?? r.category, r.count])} />}>
      <ul className="space-y-1.5">
        {rows.map((r, i) => (
          <li key={r.code} className="grid grid-cols-[minmax(4rem,9rem)_1fr] items-center gap-2">
            <span className="text-sm truncate text-right">{r.name}</span>
            <div className="flex items-center gap-1.5 min-w-0">
              <div className="relative h-[18px] rounded-r outline-none" tabIndex={0} aria-label={`${r.name}: ${r.count}건`}
                   style={{ width: `${(r.count / max) * 100}%`, minWidth: 4, background: C_ONE }}
                   onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                {hover === i && <Tip lines={[`${r.name} (${CAT[r.category] ?? r.category})`, `${r.count}건 · ${Math.round((r.count / s.total) * 100)}%`]} />}
              </div>
              <span className="text-sm tabular-nums text-ink-muted shrink-0">{r.count}</span>
            </div>
          </li>
        ))}
      </ul>
    </ChartCard>
  )
}

/** 기간 안의 모든 달을 채운다(등록이 없는 달도 0 으로 보이게). */
function months(s: StatsSummary) {
  const got = new Map(s.by_month.map((m) => [m.month, m.count]))
  const out: { month: string; count: number }[] = []
  for (let d = startOfMonth(parseISO(s.start)); d <= parseISO(s.end); d = addMonths(d, 1)) {
    const k = format(d, 'yyyy-MM')
    out.push({ month: k, count: got.get(k) ?? 0 })
  }
  return out
}

function MonthChart({ s }: { s: StatsSummary }) {
  const [hover, setHover] = useState<number | null>(null)
  const data = useMemo(() => months(s), [s])
  const max = Math.max(1, ...data.map((m) => m.count))
  const H = 140
  return (
    <ChartCard title="월별 등록"
               table={<NumTable head={['월', '건수']} rows={data.map((m) => [m.month, m.count])} />}>
      <div className="overflow-x-auto">
        {/* 위 여백은 가장 긴 막대의 말풍선이 잘리지 않을 만큼 */}
        <div className="flex gap-2 pt-10 border-b border-surface-border" style={{ height: H + 40 }}>
          {data.map((m, i) => (
            <div key={m.month} className="relative flex-1 min-w-[2.5rem] flex justify-center">
              <div className="absolute bottom-0 w-6 max-w-full rounded-t outline-none" tabIndex={0} aria-label={`${m.month}: ${m.count}건`}
                   style={{ height: Math.max(m.count ? 2 : 0, (m.count / max) * H), background: C_ONE }}
                   onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                <span className="absolute bottom-full mb-0.5 left-1/2 -translate-x-1/2 text-xs tabular-nums text-ink-muted">{m.count}</span>
                {hover === i && <Tip lines={[m.month, `${m.count}건`]} />}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-2 pt-0.5">
          {data.map((m) => <span key={m.month} className="flex-1 min-w-[2.5rem] text-center text-xs text-ink-faint tabular-nums">{m.month.slice(2).replace('-', '.')}</span>)}
        </div>
      </div>
    </ChartCard>
  )
}

function NumTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="w-full text-base">
      <thead className="text-sm text-ink-muted sticky top-0 bg-surface">
        <tr>{head.map((h, i) => <th key={h} className={`font-medium py-1 ${i ? 'text-right' : 'text-left'}`}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={String(r[0])} className="border-t border-surface-border/60">
            {r.map((v, i) => <td key={i} className={`py-1 ${i ? 'text-right tabular-nums' : ''}`}>{typeof v === 'number' ? v.toLocaleString() : v}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
