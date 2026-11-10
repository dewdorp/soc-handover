import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { ArrowRight, Inbox, Send } from 'lucide-react'
import { handoverApi } from '@/services/api/handovers'
import { shiftApi, type InboxItem } from '@/services/api/shift'
import { taskApi, type MyWorkItem } from '@/services/api/tasks'
import Inspections from '@/features/calendar/Inspections'
import MySchedules from '@/features/calendar/MySchedules'
import ClosingCheck from '@/features/shift/ClosingCheck'
import { fieldLabel } from '@/features/handovers/VersionHistory'
import { useFeatures } from '@/hooks/useAuth'
import type { Filter } from '@/types/handover'

/**
 * KPI 는 인수인계 목록의 Quick Filter · 필터와 **같은 조건**으로 센다.
 * 숫자를 누르면 그 조건 그대로 목록이 열리므로, 대시보드 숫자와 목록 건수가 어긋날 수 없다
 * (UI_STRUCTURE §2 — 단순 숫자 표시 금지).
 */
interface Kpi { key: string; label: string; hint?: string; quick: string[]; filters?: Filter[]; tone?: string }

const KPI: Kpi[] = [
  { key: 'new_today', label: '금일 신규', quick: ['TODAY'] },
  { key: 'in_progress', label: '진행 중', quick: ['IN_PROGRESS'] },
  { key: 'need_ack', label: '내 확인 필요', hint: '내가 확인하거나 다시 확인해야 할 것', quick: ['NEED_ACK'], tone: 'text-state-check' },
  { key: 'important', label: '중요', hint: '미완료인 중요 업무', quick: ['IMPORTANT', 'OPEN'] },
  { key: 'due_today', label: '오늘 수행 예정', hint: '수행일이 오늘인 미완료',
    quick: ['OPEN'], filters: [{ field: 'work_date', op: 'between', value: 'TODAY' }] },
  { key: 'overdue', label: '지연', hint: '수행일이 지났는데 끝나지 않은 것', quick: ['OVERDUE'], tone: 'text-state-urgent' },
]

function listUrl(k: Pick<Kpi, 'quick' | 'filters'>): string {
  const params = new URLSearchParams()
  if (k.quick.length) params.set('quick', k.quick.join(','))
  if (k.filters?.length) params.set('f', JSON.stringify(k.filters))
  return `/handovers?${params.toString()}`
}

function Retry({ onRetry }: { onRetry: () => void }) {
  return <button className="btn btn-sm" onClick={onRetry}>다시 시도</button>
}

function WorkRow({ item }: { item: MyWorkItem }) {
  const target = {
    TASK: [`/my-work?task=${item.id}`, '할일 열기'],
    SCHEDULE: [`/my-work?schedule=${item.id}`, '일정 보기'],
    HANDOVER: [`/handovers?id=${item.id}`, '인수인계 보기'],
    ACK: [`/handovers?id=${item.handover_id ?? item.id}`, item.ack_state === 'REACK_REQUIRED' ? '변경 보기' : '내용 보기'],
  }[item.kind]
  const date = item.kind === 'SCHEDULE' && item.start_at
    ? format(parseISO(item.start_at), item.all_day ? 'yyyy-MM-dd' : 'yyyy-MM-dd HH:mm') : item.due
  return <li>
    <Link to={target[0]} className="block rounded py-2 hover:bg-surface-sunken">
      <span className="block break-words font-medium">{item.title}</span>
      <span className="flex flex-wrap items-center gap-x-2 text-sm text-ink-muted">
        {item.company && <span className="break-words">{item.company}</span>}
        <span>{date || '날짜 미지정'}</span><span className="text-brand">{target[1]} →</span>
      </span>
    </Link>
  </li>
}

function WorkBucket({ bucket, label }: { bucket: 'today' | 'overdue'; label: string }) {
  const work = useQuery({ queryKey: ['my-work', bucket, 'all'], queryFn: () => taskApi.myWork(bucket, 'all'),
    staleTime: 30_000, refetchInterval: 60_000 })
  return <section className="min-w-0">
    <h3 className="border-b border-surface-border pb-2 font-semibold">
      <Link to={`/my-work?bucket=${bucket}`} className="hover:underline">{label}
        {work.data && <span className={`ml-2 tabular-nums ${bucket === 'overdue' && work.data.counts.overdue ? 'text-state-urgent' : 'text-brand'}`}>{work.data.counts[bucket]}건</span>}
      </Link>
    </h3>
    {work.isError && <p className="my-2 text-sm">{work.data ? '업무 갱신에 실패했습니다. 마지막 조회 결과입니다.' : '업무를 불러오지 못했습니다.'} <Retry onRetry={() => work.refetch()} /></p>}
    {work.isPending && <p className="py-3 text-ink-muted">불러오는 중…</p>}
    {work.data && (work.data.items.length
      ? <ul className="divide-y divide-surface-border">{work.data.items.slice(0, 3).map(item => <WorkRow key={`${item.kind}-${item.id}`} item={item} />)}</ul>
      : !work.isError && <p className="py-3 text-sm text-ink-muted">{label} 업무가 없습니다.</p>)}
  </section>
}

function InboxRow({ row }: { row: InboxItem }) {
  const reack = row.state === 'REACK_REQUIRED'
  const prior = reack ? row.acked_version_no : row.version_no_at_transfer
  return <li>
    <Link to={`/handovers?id=${row.handover_id}`} className="block rounded py-2 hover:bg-surface-sunken">
      <span className="block break-words font-medium">{row.title}</span>
      <span className="block break-words text-sm text-ink-muted">
        {row.priority_code === 'URGENT' && <strong className="mr-1 text-state-urgent">긴급</strong>}
        {row.company && `${row.company} · `}{reack ? '확인 후 변경' : '확인 대기'}
        {prior != null && prior < row.current_version_no && ` · ${reack ? '확인' : '인계'} v${prior} →`}
        {' '}현재 v{row.current_version_no}{row.from_user && ` · ${row.from_user}`}
      </span>
      {!!row.stale_reason?.length && <span className="block break-words text-sm text-ink-muted">변경 항목 · {row.stale_reason.map(fieldLabel).join(', ')}</span>}
      <span className="text-sm text-brand">{reack ? '최신 내용 보기' : '내용 보기'} →</span>
    </Link>
  </li>
}

export default function DashboardPage() {
  const system = useFeatures()
  const features = system.data
  const inbox = useQuery({ queryKey: ['inbox'], queryFn: shiftApi.inbox, staleTime: 15_000, refetchInterval: 30_000 })
  const preview = inbox.data?.slice().sort((a, b) => Number(b.priority_code === 'URGENT') - Number(a.priority_code === 'URGENT')).slice(0, 3)
  const counts = useQueries({ queries: KPI.map(k => ({ queryKey: ['kpi', k.key],
    queryFn: () => handoverApi.search({ quick: k.quick, filters: k.filters ?? [], page: 1, size: 1 }),
    staleTime: 30_000, refetchInterval: 60_000 })) })

  return <div className="mx-auto max-w-screen-2xl space-y-4 p-3 sm:p-5">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <h1 className="text-xl font-semibold tracking-tight">근무 대시보드</h1>
      <Link className="btn" to="/shift"><Send size={14} /> 다음 교대에 인계하기</Link>
    </header>
    <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <section className="card min-w-0 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Inbox size={17} className="text-brand" /> 인수 확인
            {inbox.data && <span className="text-state-check">{inbox.data.length}건</span>}</h2>
          <Link className="text-sm text-brand hover:underline" to="/shift/inbox">확인함 전체 →</Link>
        </div>
        {inbox.isError && <p className="mt-3">{inbox.data ? '확인함 갱신에 실패했습니다. 마지막 조회 결과입니다.' : '확인함을 불러오지 못했습니다.'} <Retry onRetry={() => inbox.refetch()} /></p>}
        {inbox.isPending && <p className="mt-3 text-ink-muted">불러오는 중…</p>}
        {preview && (preview.length
          ? <ul className="mt-2 divide-y divide-surface-border">{preview.map(row => <InboxRow key={row.handover_id} row={row} />)}</ul>
          : !inbox.isError && <p className="mt-3 text-ink-muted">확인할 인수인계가 없습니다.</p>)}
      </section>
      <ClosingCheck />
      {/* 오늘 돌 점검이 없으면 자리를 차지하지 않는다(compact) */}
      <Inspections compact />
      <section className="card min-w-0 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">내 업무 요약</h2>
          <div className="flex items-center gap-3 text-sm text-brand">
            <Link className="hover:underline" to="/my-work/notes">내 메모</Link>
            <Link className="hover:underline" to="/my-work">내 업무 전체 →</Link>
          </div></div>
        <div className="mt-3 grid gap-4 sm:grid-cols-2"><WorkBucket bucket="overdue" label="지연" /><WorkBucket bucket="today" label="오늘" /></div>
      </section>
    </div>
    <MySchedules />
    <section aria-label="인수인계 현황">
      <h2 className="mb-2 text-lg font-semibold">인수인계 현황</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPI.map((k, i) => <Link key={k.key} to={listUrl(k)} title={k.hint} className="card min-w-0 p-3 hover:border-brand">
          <span className="flex items-center justify-between gap-1 text-sm font-medium text-ink-muted">{k.label}<ArrowRight size={12} /></span>
          <span className={`mt-1 block text-2xl font-semibold tabular-nums ${counts[i].data?.total ? k.tone ?? 'text-ink' : 'text-ink-faint'}`}>
            {counts[i].data?.total.toLocaleString() ?? <span className="text-sm">{counts[i].isError ? '조회 실패' : '조회 중…'}</span>}
          </span></Link>)}
      </div>
      {counts.some(q => q.isError) && <p className="mt-2 text-sm">일부 지표를 불러오지 못했습니다. <Retry onRetry={() => counts.filter(q => q.isError).forEach(q => q.refetch())} /></p>}
    </section>
    {features?.database_warning && <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-state-check">{features.database} · {features.database_warning}</p>}
  </div>
}
