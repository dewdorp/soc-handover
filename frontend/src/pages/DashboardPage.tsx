import { useQueries, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Database, ShieldCheck } from 'lucide-react'
import { api } from '@/services/api/client'
import { handoverApi } from '@/services/api/handovers'
import { useFeatures, useMe } from '@/hooks/useAuth'
import type { Company, HandoverStatus, Shift } from '@/types/api'
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
  { key: 'need_ack', label: '확인 필요', hint: '내가 확인하거나 다시 확인해야 할 것', quick: ['NEED_ACK'], tone: 'text-state-check' },
  { key: 'important', label: '중요', hint: '미완료인 중요 업무', quick: ['IMPORTANT', 'OPEN'] },
  { key: 'due_today', label: '오늘 마감', hint: '수행일이 오늘인 미완료',
    quick: ['OPEN'], filters: [{ field: 'work_date', op: 'between', value: 'TODAY' }] },
  { key: 'overdue', label: '지연', hint: '수행일이 지났는데 끝나지 않은 것', quick: ['OVERDUE'], tone: 'text-state-urgent' },
]

function listUrl(k: Pick<Kpi, 'quick' | 'filters'>): string {
  const params = new URLSearchParams()
  if (k.quick.length) params.set('quick', k.quick.join(','))
  if (k.filters?.length) params.set('f', JSON.stringify(k.filters))
  return `/handovers?${params.toString()}`
}

export default function DashboardPage() {
  const { data: me } = useMe()
  const { data: features } = useFeatures()
  const companies = useQuery({ queryKey: ['companies'], queryFn: () => api.get<Company[]>('/companies') })
  const statuses = useQuery({ queryKey: ['statuses'], queryFn: () => api.get<HandoverStatus[]>('/statuses') })
  const shifts = useQuery({ queryKey: ['shifts'], queryFn: () => api.get<Shift[]>('/shifts') })
  const navigate = useNavigate()
  const counts = useQueries({
    queries: KPI.map((k) => ({
      queryKey: ['kpi', k.key],
      queryFn: () => handoverApi.search({ quick: k.quick, filters: k.filters ?? [], page: 1, size: 1 }),
      staleTime: 30_000,
      refetchInterval: 60_000,
    })),
  })

  return (
    <div className="p-3 space-y-3">
      {(me?.pending_ack_count ?? 0) > 0 && (
        <div className="card px-3 py-2 flex items-center gap-2 border-amber-300 bg-amber-50">
          <AlertTriangle size={15} className="text-amber-600" />
          <span className="text-sm">
            확인하지 않은 인수인계 <b>{me?.pending_ack_count}건</b>이 있습니다.
          </span>
          <button className="btn btn-sm ml-auto" onClick={() => navigate(listUrl({ quick: ['NEED_ACK'] }))}>
            확인하러 가기
          </button>
        </div>
      )}

      <div className="grid grid-cols-6 gap-2">
        {KPI.map((k, i) => {
          const total = counts[i].data?.total
          return (
            <button key={k.key} onClick={() => navigate(listUrl(k))} title={k.hint}
                    className="card px-3 py-2 text-left hover:border-brand focus-visible:border-brand">
              <div className="text-xs text-ink-faint">{k.label}</div>
              <div className={`text-lg font-semibold tabular-nums ${total ? (k.tone ?? 'text-ink') : 'text-ink-faint'}`}>
                {total === undefined ? '–' : total.toLocaleString()}
              </div>
            </button>
          )
        })}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <section className="card p-3">
          <h2 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <ShieldCheck size={14} className="text-brand" /> 시스템 상태
          </h2>
          <dl className="text-sm grid grid-cols-[110px_1fr] gap-y-1">
            <dt className="text-ink-muted">데이터베이스</dt>
            <dd className="flex items-center gap-1.5">
              <Database size={13} className="text-ink-faint" />
              {features?.database ?? '-'}
              {features?.database_warning && (
                <span className="text-amber-700 text-xs">({features.database_warning})</span>
              )}
            </dd>
            <dt className="text-ink-muted">AI 기능</dt>
            <dd>{features?.ai_enabled ? '사용' : '사용 안 함 (기본값)'}</dd>
            <dt className="text-ink-muted">관계사</dt>
            <dd>{companies.data?.length ?? 0}개</dd>
            <dt className="text-ink-muted">상태 코드</dt>
            <dd>{statuses.data?.length ?? 0}개</dd>
            <dt className="text-ink-muted">교대 정의</dt>
            <dd>
              {shifts.data?.map((s) => `${s.name} ${s.start_time.slice(0, 5)}`).join(' · ') || '-'}
            </dd>
            <dt className="text-ink-muted">재확인 필드</dt>
            <dd className="truncate" title={features?.ack.reack_fields.join(', ')}>
              {features?.ack.reack_fields.length ?? 0}개
            </dd>
          </dl>
        </section>

        <section className="card p-3">
          <h2 className="text-sm font-semibold mb-2">구현 현황</h2>
          <ul className="text-sm space-y-1">
            <li>✔ Phase 0 — 설계 문서 7종</li>
            <li>✔ Phase 1 — 인증 · RBAC · 감사 기반 · Windows 실행환경</li>
            <li>✔ Phase 2 — 인수인계 CRUD · Version · Diff · 복원</li>
            <li>✔ Phase 3 — Data Grid · 컬럼 필터 · 검색 · 저장된 보기</li>
            <li>✔ Phase 4 — Excel Import/Export</li>
            <li className="text-ink-faint">· Phase 5 — 교대 인수인계 · 확인 · Carry Forward</li>
            <li className="text-ink-faint">· Phase 6~10 — Task · 일정 · 감사 UI · AI(선택) · 안정화</li>
          </ul>
        </section>
      </div>
    </div>
  )
}
