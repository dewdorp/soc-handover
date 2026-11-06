# 메뉴 매핑 — 요구가 화면 어디에 있고, 무엇이 그것을 지키는가

이 표는 "그 기능이 어디 있느냐"는 물음에 한 줄로 답하기 위한 것이다. 왼쪽이 요구,
가운데가 화면 위치, 오른쪽이 그 동작을 **실제로 확인하는 시험**이다.

## 1. 왼쪽 메뉴

| 메뉴 | 주소 | 하위 탭 |
|---|---|---|
| 대시보드 | `/` | — (교대 마감 점검 · 인수 확인 · 내 업무 요약 · 내 일정 · 인수인계 현황) |
| 인수인계 | `/handovers` | 인수인계 기록 · 인계 준비 · 인수 확인함 · 인계 이력 |
| 내 업무 | `/my-work` | 내 담당 업무 · 내 메모 · 팀 할일 · 팀 일정 · 근무표 |
| 일정 · 근무표 | `/schedules` | 팀 일정 · **정기 점검** · 근무표 |
| 비밀번호 | `/credentials` | — (교대 공용 · 개인 목록 · 일괄 열람) |
| 운영 지식 | `/knowledge` | — (절차 · 탐지 분석 · 비상 대응 · 장비 · 점검 · 참고) |
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

### ⑥ 1.3.1 운영 편의성

| 요구 | 화면 위치 | API | 시험 |
|---|---|---|---|
| 설정 화면 오류(`m.join is not a function`) | 설정 | `GET /settings` | `test_ops_patch_flows.py::test_settings_page_renders_every_category` |
| 근무표 기준일이 날짜 칸으로 | 설정 → 근무표 | `PATCH /settings/roster.epoch_date` | 같은 시험(`type="date"` 확인) |
| 값 하나가 화면 전체를 막지 않음 | 설정(줄 단위 울타리) | — | `test_one_bad_setting_value_does_not_blank_the_page` |
| 저장 실패 원인 · 재시도 | 설정 각 줄 | `PATCH /settings/{key}` | `RowErrorBoundary` · 화면 시험 |
| 감사 소음 줄이기 · 열람 기록 켜기 | 감사로그 · 설정 → 감사로그 | `audit.track_handover_views` | `test_handover_view_audit_optional`, `test_audit_simplification_keeps_the_evidence_that_matters` |
| 막힌 열람은 남긴다 | 감사로그 | `POST /handovers/{id}/view` | `test_failed_view_is_still_recorded` |
| 중요도별 빠른 보기 네 갈래 | 감사로그 → 행위 선택 | `GET /audit/catalog` (`views`) | `audit_service.ACTION_VIEWS` · 위 시험 |
| 그룹 미지정 = 전체 공개 | 등록 창 · 상세(편집) | `visibility` 기본 `ALL` | `test_ungrouped_handover_public_and_explicit_group_restricted` |
| 빈 그룹 목록으로 조용히 공개 금지 | — (서버) | `PATCH /handovers/{id}` | `test_empty_group_list_cannot_silently_publish_a_restricted_handover` |
| 담당자가 그룹 밖이면 저장 전 경고 | 등록 창 · 상세(편집) | `POST /groups/scope-check` | `test_scope_check_warns_about_assignees_without_group_access` |
| 과거 자료 전환(건수 · 목록 · 경고 · 승인 · 되돌리기) | 관리자 → 열람 그룹 | `/groups/public-migration/*` | `test_legacy_conversion_needs_preview_phrase_and_backup`, E2E `test_legacy_conversion_requires_typed_confirmation` |
| 업데이트만으로는 공개되지 않음 | — (마이그레이션) | `c60e8b91f4a2` | `test_upgrade_1_2_to_1_3.py::test_upgrading_alone_publishes_nothing` |
| 운영 지식(등록 · 분류 · 태그 · 검색 · 고정 · 재검토) | **운영 지식** `/knowledge` | `/knowledge` | `test_knowledge_article_groups_and_file_download` |
| 개정 이력 · 판 비교 · 복원 | 운영 지식 → 문서 하단 | `/knowledge/{id}/revisions*` | `test_knowledge_revisions_compare_and_restore`, E2E |
| 삭제 · 복원 | 운영 지식 → 문서 머리 | `DELETE`/`POST .../restore` | `test_knowledge_soft_delete_and_restore` |
| 표준 양식(7절) | 운영 지식 → 새 문서 | `GET /knowledge/template` | `test_knowledge_template_and_keyword_suggestion` |
| 첨부가 문서 권한을 상속 | 운영 지식 → 첨부 문서 | `/attachments?entity_type=KNOWLEDGE` | `test_knowledge_article_groups_and_file_download` |
| 인계 ↔ 절차 연결 · 키워드 추천 | 인계 상세 '관련 운영 지식' · 운영 지식 '관련 인수인계' | `/knowledge/{id}/handovers`, `/knowledge/suggest` | `test_knowledge_links_do_not_widen_handover_access` |
| 금고 일괄 열람(5분 · 연장 · 지금 잠그기) | 비밀번호 | `/credentials/vault/*` | `test_bulk_vault_unlock_restricts_personal_and_locks`, E2E `test_vault_bulk_view_extend_and_lock` |
| 15분 상한 · 설정으로도 못 넘김 | 설정 → 비밀번호 | `credential.max_session_minutes` | `test_vault_session_cannot_be_configured_beyond_fifteen_minutes` |
| 권한이 바뀌면 즉시 잠금 | 비밀번호(20초마다 서버 확인) | `GET /credentials/vault/status` | `test_vault_session_dies_when_groups_or_role_change` |
| 남의 개인 비밀번호는 일괄로도 안 보임 | 비밀번호 | `/credentials/vault/secrets` | `test_bulk_vault_unlock_...`, E2E `test_vault_does_not_show_another_persons_personal_password` |
| 정기 점검(주기 · 담당자 · 완료) | 대시보드 '오늘 점검' · 일정 → 정기 점검 | `/schedules/inspections`, `/schedules/{id}/completions` | `test_recurring_inspection_completion_per_occurrence`, E2E `test_inspection_checklist_completes_on_the_dashboard` |
| 교대 마감 점검에 점검 포함 | 대시보드 | `GET /shift-handovers/closing-check` | `test_closing_check_counts_pending_inspections` |

## 3. 넣지 않은 것과 그 이유

요구 중 다음은 **일부러 넣지 않았다**. 메뉴와 할 일 목록이 늘어나는 값보다
잃는 것이 크다고 판단한 것들이다.

| 넣지 않은 것 | 이유 | 대신 쓰는 것 |
|---|---|---|
| '정기 점검' 별도 메뉴 | 할 일이 인계 · 할일 · 점검 셋으로 쪼개지면 야간에 혼자 보는 사람이 어느 목록을 봐야 하는지부터 헷갈린다 | `event_type=INSPECTION` 반복 일정 + 회차별 완료. 대시보드 '오늘 점검'과 교대 마감 점검에 함께 나온다 |
| '빠른 링크' 모음 화면 | 왼쪽 메뉴가 이미 9개다. 링크를 모으는 화면을 또 두면 찾는 곳이 둘이 된다 | 왼쪽 메뉴 + 즐겨찾기(별표) + `Ctrl+K` 통합 검색 |
| '즐겨찾기' 전용 메뉴 | 별표는 이미 인계 목록에서 걸고 거른다 | 인수인계 목록의 별표 필터 |
| '내 알림만 보기' 별도 화면 | 알림은 본래 내 것만 온다(개인 단위로 만든다) | 상단 알림 종 · 팝업 |
| 메모 → 인계 '초안' 상태 | 초안을 따로 두면 '아직 안 보낸 것'이 메모 · 초안 · 바구니 셋으로 늘어난다 | 내 메모에서 '인계로 올리기'(내용을 들고 등록 창을 연다) |
| 비밀번호 그룹별 공개 | 야간 단독 근무자가 '내 그룹이 아니어서' 장비를 못 열면 그것이 곧 대응 지연이다. 적용 범위를 먼저 정해야 한다(SECURITY.md 10-3) | SHARED/PERSONAL + 관계사 필터 + 계정에 `credential:read` 를 주지 않기 |
| 운영 지식 AI 요약 · 자동 분류 | 폐쇄망이고 모델이 없다. 추천은 규칙 기반으로 충분히 맞는다 | 제목 낱말 기반 추천(`/knowledge/suggest`) · 태그 · 검색 |

---

## 4. 권한 한눈에

| 권한 | 누구 | 무엇을 |
|---|---|---|
| `group:manage` | 관리자 | 그룹 만들기 · 구성원 · 자료 이관. **원문 열람 권한이 아니다** |
| `shift:manage` | 관리자 | 조 편성 · 대근 · 맞교환 · 기준일 |
| `handover:update_own` | 모두(본인 건) | 담당 · 전파 대상 **바꾸기**(사람을 뺄 수 있어서) |
| `handover:read` | 모두 | 그룹 전파(더하기만) · 분석 의뢰 · 접수 · 회신 |
| `schedule:read` | 모두 | 근무표 보기 |
| `export:run` | 모두 | Excel · RAG 사례 묶음(둘 다 '대량으로 꺼내기'라 같은 권한) |
| `credential:read` | 모두 | 비밀번호 목록(값은 본인 확인 후에만) |
