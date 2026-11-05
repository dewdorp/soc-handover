# 메뉴 매핑 — 요구가 화면 어디에 있고, 무엇이 그것을 지키는가

이 표는 "그 기능이 어디 있느냐"는 물음에 한 줄로 답하기 위한 것이다. 왼쪽이 요구,
가운데가 화면 위치, 오른쪽이 그 동작을 **실제로 확인하는 시험**이다.

## 1. 왼쪽 메뉴

| 메뉴 | 주소 | 하위 탭 |
|---|---|---|
| 대시보드 | `/` | — (교대 마감 점검 · 인수 확인 · 내 업무 요약 · 내 일정 · 인수인계 현황) |
| 인수인계 | `/handovers` | 인수인계 기록 · 인계 준비 · 인수 확인함 · 인계 이력 |
| 내 업무 | `/my-work` | 내 담당 업무 · 내 메모 · 팀 할일 · 팀 일정 · 근무표 |
| 일정 · 근무표 | `/schedules` | 팀 일정 · **근무표** |
| 비밀번호 | `/credentials` | — (교대 공용 · 개인 목록) |
| Excel Import/Export | `/import` | 올리기 → 열 맞추기 → 미리보기 → 반영 |
| 통계 | `/stats` | — |
| 감사로그 | `/audit` | — |
| 관리자 | `/admin/users` | 사용자 · **열람 그룹** · 상태/관계사 · 교대 시간 · 백업 |
| 설정 | `/settings` | — |

## 2. 요구 → 위치 → 시험

### ① 재현된 오류 수정

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 읽지 않은 버전이 확인 처리됨 | 인수 확인함 · 상세 서랍 | `POST /handovers/{id}/acknowledge` (`expected_version`), `POST /acknowledgements/bulk` | `test_shift_api.py::TestAckUsesTheVersionOnScreen` |
| 09:01 발송이 당일 주간으로 | 인계 준비 | `GET /shift-handovers/basket/send-check`, `POST …/send` (`confirm_window`) | `TestShiftBoundary` |
| 복수 발신자 중 한쪽만 이월 | 인계 준비 | `GET …/basket/carry-forward-candidates` | `TestCarryForwardFromManySenders` |
| 공용 PC 에 앞사람 검색어 | 상단 검색 | (브라우저 저장소를 쓰지 않는다) | `frontend/src/features/search/recent.ts` · E2E |
| 가져오기 `UNSPEC` 충돌 · 중단/복구 | Excel Import | `POST /import/jobs/{id}/cancel` | `test_import_unspec.py` |

### ② 열람 그룹

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 그룹 만들기 · 이름 · 사용 중지 | 관리자 → 열람 그룹 | `GET/POST/PATCH /groups` | `test_group_acl.py::TestGroupAdministration` |
| 사람별 소속 · 기본 그룹 | 관리자 → 열람 그룹 → 구성원 | `GET/PUT /users/{id}/groups` | 같은 파일 |
| 글마다 공개 범위 | 등록 창 · 상세 서랍(편집) | `visibility`, `group_ids` | `TestOtherGroupsAreNotListed` |
| 서버 강제(목록·건수·상세·첨부·댓글·이력·검색·알림·통계·Excel·토큰) | 전부 | `search_service` / `handover_service.get_or_404` 한 곳 | `TestDirectUrlIsClosed`, `TestRevocationTakesEffectImmediately` |
| 관리자 우회 금지 | — | 역할은 열람 판정에 쓰지 않는다 | `TestAdminHasNoBackDoor` |
| 미분류 자료 이관 | 관리자 → 열람 그룹 → 아래 이관 패널 | `GET/POST /groups/unclassified/*` | `test_unclassified_data_moves_without_becoming_public` |

### ③ 근무표 · 대근 · CERT

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 4조 2교대 16일 주기 | 일정 · 근무표 → 근무표 | `GET /roster/calendar?view=week\|month` | `test_roster_api.py::TestCycle` |
| 야간 = 시작 날짜 기준 | 같은 화면 | `GET /roster/day` | `TestNightIsKeyedToItsStartDate` |
| 내 근무 | 근무표 아래 '내 근무 (14일)' | `GET /roster/mine` | `TestRecipientSuggestion` |
| 실근무자 | 근무표의 각 줄(취소선·굵게) | `GET /roster/day` | `TestSubstitution` |
| 1인 대근 · 맞교환 · 취소/복원 | 줄 오른쪽 버튼 | `POST /roster/overrides`, `/roster/swaps`, `…/cancel` | `TestSubstitution`, `TestSwap` |
| 이중 배정 금지 | 서버가 거절(409) | 같은 API | `TestNoDoubleBooking` |
| 3/4 결원 표시 | 줄에 `3/4 결원 1명` | `GET /roster/day` | `test_absence_without_cover_is_marked_short` |
| 변경 이력 · 알림 | 줄 아래 변경 목록 · 알림함 | `GET /roster/overrides` | `test_history_keeps_canceled_rows` |
| 인계 상대 추천 | 인계 준비 → '실근무자로 채우기' | `GET /roster/next-shift` | `test_substitute_shows_up_in_the_suggestion` |

### ③-2 복수 담당 · CERT 전파 · 분석 의뢰

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 대표 · 공동 담당 | 상세 서랍 → 담당 · 전파 대상 | `PUT /handovers/{id}/participants` | `test_participants_and_request.py::TestRolesAreDeduplicated` |
| 필수 인수자 · 참고 전파자 | 같은 자리의 역할 선택 | 같은 API | `test_fyi_does_not_create_a_pending_ack` |
| 같은 사람이 두 역할이면 | 서버가 강한 쪽만 남긴다 | 같은 API | `test_same_person_twice_keeps_the_stronger_role` |
| CERT 전체 전파 · 받는 사람 미리보기 | 상세 서랍 → '그룹에 전파' | `POST /handovers/{id}/propagate/preview` | `TestPropagation` |
| 담당 N / 필수 N / 참고 N / 제외 M | 전파 창 안 | 같은 API | `test_preview_shows_who_and_how_many` |
| 전파가 공개 범위를 넓히지 않는다 | 전파 창의 안내 문구 | `POST …/propagate` | `test_propagation_does_not_widen_the_public_scope` |
| 분석 의뢰 → 접수 → 회신 | 상세 서랍 → 분석 의뢰 | `POST …/request`, `…/request/accept`, `…/request/answer` | `TestAnalysisRequest` |
| 목록에서 '의뢰 중' 보기 | 인수인계 목록의 '의뢰' 열 | 목록 응답의 `request_state` | `test_request_state_is_on_the_list_row` |

### ④ 대시보드 · 일정 알림 · 메모 연결

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 교대 마감 점검(누르면 목록) | 대시보드 상단 | `GET /shift-handovers/closing-check` | `test_closing_and_reminders.py::TestClosingCheck` |
| 다음 근무 결원 경고 | 같은 카드 마지막 줄 | 같은 API | `test_next_shift_shortage_is_surfaced` |
| 내 일정 7일 · 회차 ≤3 | 대시보드 하단 | `GET /schedules/mine` | `TestMySchedules` |
| 일정별 내 알림(끄기/시작/10·30분/직접) | 같은 카드의 선택기 | `PUT /schedules/{id}/reminder` | `TestScheduleReminder` |
| 알림 전달 | 기존 알림함 | `jobs/reminders.run_schedule_reminders` | `test_job_sends_once_per_occurrence` |
| 메모 → 내 할 일 / 인계 초안 | 내 업무 → 내 메모 (내용 선택 시 나타남) | 기존 `POST /tasks`, 등록 창 | 선택한 글만 전달 · 역방향 링크 없음 |

### ⑤ RAG 바닥 공사

| 요구 | 위치 | API | 시험 |
|---|---|---|---|
| 사례 데이터 구조 | `docs/RAG.md` §2 | `GET /rag/contract` (`fields`) | `test_rag_groundwork.py::TestContract` |
| 접근 계약 | `docs/RAG.md` §3 | `GET /rag/contract` (`rules`) | `test_contract_requires_db_recheck_not_index_trust` |
| 제외 자료 | `docs/RAG.md` §4 | 같은 API (`excluded`) | `TestExcludedSourcesNeverLeak` |
| 검증 예시 | `docs/RAG.md` §5 | `GET /rag/verification-examples` | `test_verification_examples_cover_the_boundaries` |

## 3. 권한 한눈에

| 권한 | 누구 | 무엇을 |
|---|---|---|
| `group:manage` | 관리자 | 그룹 만들기 · 구성원 · 자료 이관. **원문 열람 권한이 아니다** |
| `shift:manage` | 관리자 | 조 편성 · 대근 · 맞교환 · 기준일 |
| `handover:update_own` | 모두(본인 건) | 담당 · 전파 대상 **바꾸기**(사람을 뺄 수 있어서) |
| `handover:read` | 모두 | 그룹 전파(더하기만) · 분석 의뢰 · 접수 · 회신 |
| `schedule:read` | 모두 | 근무표 보기 |
| `export:run` | 모두 | Excel · RAG 사례 묶음(둘 다 '대량으로 꺼내기'라 같은 권한) |
| `credential:read` | 모두 | 비밀번호 목록(값은 본인 확인 후에만) |
