import PhasePlaceholder from '@/components/ui/PhasePlaceholder'

export const AiSearchPage = () => (
  <PhasePlaceholder title="AI 검색" phase="Phase 9 (선택 기능)" items={[
    '자연어 질문 → 구조화 조건 추출 → 메타데이터 필터',
    'Full Text + Vector 하이브리드 검색 및 RRF 병합',
    '근거(Source) 없는 답변 금지 — 없으면 "찾지 못했습니다"',
  ]} />
)

export const NotFoundPage = () => (
  <div className="p-8 text-sm text-ink-muted">요청하신 화면을 찾을 수 없습니다.</div>
)
