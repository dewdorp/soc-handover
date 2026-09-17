import PhasePlaceholder from '@/components/ui/PhasePlaceholder'

export const HandoverListPage = () => (
  <PhasePlaceholder title="인수인계" phase="Phase 2~3" items={[
    'Excel 스타일 Dense Data Grid (Compact/Normal/Comfortable)',
    '컬럼 헤더 필터 3종(값 선택 · 텍스트 조건 · 날짜 Quick Filter)',
    '적용 필터 Chip · Quick Filter · Global Search',
    '우측 Drawer 상세(상세/할일/일정/전달이력/변경이력/첨부)',
    'Version 이력 · Diff · 복원 · 낙관적 잠금 충돌 처리',
  ]} />
)

export const ShiftPage = () => (
  <PhasePlaceholder title="교대 인수인계" phase="Phase 5" items={[
    'Cockpit 6영역(근무 중 신규/진행 중/확인 필요/다음 근무 예정/중요/지연)',
    '인계 Basket 담기 · 순서 조정 · 수신자 지정',
    '인계 실행 시 항목별 전달 버전 고정 · 확인(ack) 생성',
    '확인 이후 변경 시 재확인 필요 자동 전환',
    '미완료 업무 Carry Forward(복제 없이 동일 건 연결)',
  ]} />
)

export const MyWorkPage = () => (
  <PhasePlaceholder title="내 업무" phase="Phase 6" items={[
    '오늘/지연/이번주/예정/대기/완료 버킷',
    '담당 인수인계 + 내 Task + 확인 대기 + 내 일정 통합',
    'List / Board / Calendar 전환',
  ]} />
)

export const TaskPage = () => (
  <PhasePlaceholder title="할일" phase="Phase 6" items={[
    'Task CRUD · Checklist · Comment',
    'Kanban Board Drag&Drop 상태 변경(변경은 감사 기록)',
    '인수인계에서 Quick Add(관계사·연관 인수인계 자동 채움)',
  ]} />
)

export const SchedulePage = () => (
  <PhasePlaceholder title="일정" phase="Phase 7" items={[
    '월/주/일 캘린더',
    '일정 유형(일반·작업예정·점검·회의·보안작업·반복업무)',
    '인수인계/할일 연계 및 원본 이동',
  ]} />
)

export const SearchPage = () => (
  <PhasePlaceholder title="통합검색" phase="Phase 3" items={[
    '제목·내용·비고·관계사·인명·태그 통합 검색',
    'PostgreSQL Full Text + trigram 한글 부분일치',
    '컬럼 필터와 동시 사용 · 저장된 보기',
  ]} />
)

export const AiSearchPage = () => (
  <PhasePlaceholder title="AI 검색" phase="Phase 9 (선택 기능)" items={[
    '자연어 질문 → 구조화 조건 추출 → 메타데이터 필터',
    'Full Text + Vector 하이브리드 검색 및 RRF 병합',
    '근거(Source) 없는 답변 금지 — 없으면 "찾지 못했습니다"',
  ]} />
)

export const ImportPage = () => (
  <PhasePlaceholder title="Excel Import / Export" phase="Phase 4" items={[
    '8단계 마법사(파일→Sheet분석→매핑→미리보기→검증→중복검사→Import→결과)',
    '원본 추적(source_file/sheet/row) · Fingerprint 중복 의심 표시',
    '현재 검색 결과만 Export · Export도 감사 기록',
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

export const NotificationPage = () => (
  <PhasePlaceholder title="알림센터" phase="Phase 8" items={[
    '인수인계 배정 · 확인 필요 · 인계 후 변경 · 마감 임박/지연 알림',
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
