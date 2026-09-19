import PhasePlaceholder from '@/components/ui/PhasePlaceholder'

export const AiSearchPage = () => (
  <PhasePlaceholder title="AI 검색" phase="Phase 9 (선택 기능)" items={[
    '자연어 질문 → 구조화 조건 추출 → 메타데이터 필터',
    'Full Text + Vector 하이브리드 검색 및 RRF 병합',
    '근거(Source) 없는 답변 금지 — 없으면 "찾지 못했습니다"',
  ]} />
)

export const StatsPage = () => (
  <PhasePlaceholder title="통계" phase="Phase 8" items={[
    '관계사/상태/월별 집계',
    '확인율 · 지연 확인 통계',
  ]} />
)

export const AuditPage = () => (
  <PhasePlaceholder title="감사로그" phase="Phase 8" items={[
    'Excel 스타일 그리드(기간·사용자·Action·Resource·IP·성공실패 필터)',
    '변경 전/후 값 조회 · Excel Export',
  ]} />
)

export const AdminPage = () => (
  <PhasePlaceholder title="관리자" phase="Phase 1 · 8" items={[
    '사용자/역할 관리 API는 이미 동작합니다(Phase 1).',
    '관리 화면 UI · 상태값 편집 · 시스템 설정 · 삭제 데이터 조회는 Phase 8입니다.',
  ]} />
)

export const SettingsPage = () => (
  <PhasePlaceholder title="설정" phase="Phase 8" items={[
    '개인 설정(기본 보기·행 밀도·단축키)',
    '시스템 설정(재확인 대상 필드·첨부 정책·보존기간·AI)',
  ]} />
)

export const NotFoundPage = () => (
  <div className="p-8 text-sm text-ink-muted">요청하신 화면을 찾을 수 없습니다.</div>
)
