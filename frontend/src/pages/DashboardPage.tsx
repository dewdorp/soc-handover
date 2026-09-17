import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Database, ShieldCheck } from 'lucide-react'
import { api } from '@/services/api/client'
import { useFeatures, useMe } from '@/hooks/useAuth'
import type { Company, HandoverStatus, Shift } from '@/types/api'

/** KPI 자리. Phase 3 에서 /stats/dashboard 로 실데이터를 채운다. */
const KPI = [
  { key: 'new_today', label: '금일 신규' },
  { key: 'in_progress', label: '진행 중' },
  { key: 'need_ack', label: '확인 필요' },
  { key: 'important', label: '중요' },
  { key: 'due_today', label: '오늘 마감' },
  { key: 'overdue', label: '지연' },
]

export default function DashboardPage() {
  const { data: me } = useMe()
  const { data: features } = useFeatures()
  const companies = useQuery({ queryKey: ['companies'], queryFn: () => api.get<Company[]>('/companies') })
  const statuses = useQuery({ queryKey: ['statuses'], queryFn: () => api.get<HandoverStatus[]>('/statuses') })
  const shifts = useQuery({ queryKey: ['shifts'], queryFn: () => api.get<Shift[]>('/shifts') })

  return (
    <div className="p-3 space-y-3">
      {(me?.pending_ack_count ?? 0) > 0 && (
        <div className="card px-3 py-2 flex items-center gap-2 border-amber-300 bg-amber-50">
          <AlertTriangle size={15} className="text-amber-600" />
          <span className="text-sm">
            확인하지 않은 인수인계 <b>{me?.pending_ack_count}건</b>이 있습니다.
          </span>
          <button className="btn btn-sm ml-auto">확인하러 가기</button>
        </div>
      )}

      <div className="grid grid-cols-6 gap-2">
        {KPI.map((k) => (
          <div key={k.key} className="card px-3 py-2">
            <div className="text-xs text-ink-faint">{k.label}</div>
            <div className="text-lg font-semibold tabular-nums text-ink-faint">–</div>
          </div>
        ))}
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
            <li className="text-ink-faint">· Phase 2 — 인수인계 CRUD · Version · Diff · 복원</li>
            <li className="text-ink-faint">· Phase 3 — Data Grid · 컬럼 필터 · 검색 · 저장된 보기</li>
            <li className="text-ink-faint">· Phase 4 — Excel Import/Export</li>
            <li className="text-ink-faint">· Phase 5 — 교대 인수인계 · 확인 · Carry Forward</li>
            <li className="text-ink-faint">· Phase 6~10 — Task · 일정 · 감사 UI · AI(선택) · 안정화</li>
          </ul>
          <p className="text-xs text-ink-faint mt-2">
            대시보드 KPI는 인수인계 데이터가 들어오는 Phase 3에서 실제 값으로 채워집니다.
          </p>
        </section>
      </div>
    </div>
  )
}
