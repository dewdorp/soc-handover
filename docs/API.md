# API.md — REST API 설계

> Base: `/api/v1` · 인증: HttpOnly Cookie(Access+Refresh) + CSRF 더블 서브밋
> 오류 형식: RFC 7807 유사 `{ "error": "<code>", "message": "<한국어>", "detail": {...}, "request_id": "..." }`
> 모든 목록 응답: `{ "items": [...], "page": 1, "size": 50, "total": 48, "total_all": 135382, "has_next": true, "cursor": null }`

---

## 0. 공통 규약

| 항목 | 규칙 |
|---|---|
| 페이징 | `page`(1-base) + `size`(기본 50, 최대 200). 깊은 페이지는 `cursor` |
| 정렬 | `sort=field:dir,field2:dir` 또는 POST 본문의 `sort[]` |
| 필터 | 단순 조회는 query string, 복합 조건은 `POST /{resource}/search` (DSL 본문) |
| 낙관적 잠금 | 수정 요청 본문에 `expected_version` 필수 → 불일치 시 409 |
| 날짜 | ISO-8601. 날짜 전용 필드는 `YYYY-MM-DD` (KST 기준) |
| 에러 코드 | `validation_error(422)`, `unauthorized(401)`, `forbidden(403)`, `not_found(404)`, `version_conflict(409)`, `rate_limited(429)`, `feature_disabled(404)`, `internal_error(500)` |

---

## 1. 인증 / 사용자

```
POST   /auth/login              {username, password}         → 200 + Set-Cookie(access, refresh, csrf)
POST   /auth/refresh                                         → 200 (refresh 회전)
POST   /auth/logout                                          → 204 (refresh 폐기)
GET    /auth/me                                              → 사용자 + 권한 + 미확인 건수
POST   /auth/change-password    {current, new}
GET    /auth/sessions           내 활성 세션 목록
DELETE /auth/sessions/{id}

GET    /users?q=&role=&active=&page=                          [MANAGER+]
POST   /users                    [ADMIN]
GET    /users/{id}
PATCH  /users/{id}               [ADMIN] (role 변경은 ROLE_CHANGE audit)
POST   /users/{id}/reset-password [ADMIN] → 1회용 임시 비밀번호 반환(화면 1회 표시)
GET    /users/lookup?q=          담당자 선택용 경량 목록(id, display_name, team)
GET    /roles
```

## 2. 기준 정보

```
GET    /companies?q=&active=          POST /companies [MANAGER+]
PATCH  /companies/{id}   DELETE /companies/{id}(비활성화)   [ADMIN]
GET    /statuses          POST/PATCH /statuses  [ADMIN]
GET    /priorities
GET    /shifts            POST/PATCH /shifts    [ADMIN]
GET    /tags?q=&limit=    POST /tags
```

## 3. 인수인계 (핵심)

```
POST   /handovers/search          ← 목록의 기본 경로 (DSL 본문)
GET    /handovers?q=&...          ← 단순 조회 / 링크 공유용 (DSL을 query로 인코딩)
GET    /handovers/facets?field=&q=&limit=   (+ 본문 대신 압축 필터 파라미터)
POST   /handovers                 생성 → v1
GET    /handovers/{id}            상세 (+ ack 상태, tag, task · schedule · comment · attachment 카운트)
GET    /handovers/{id}?as_of=<ISO>  특정 시점 상태 재현 (감사용, P-07)
PATCH  /handovers/{id}            {expected_version, change_reason?, ...fields} → 새 버전
DELETE /handovers/{id}            {reason} Soft Delete   [MANAGER+ 또는 작성자]
POST   /handovers/{id}/undelete   [ADMIN]
POST   /handovers/{id}/star       DELETE /handovers/{id}/star   (개인 즐겨찾기)
POST   /handovers/{id}/pin        [MANAGER+] (전역 상단고정)
POST   /handovers/bulk            {ids[], op: status|assignee|priority|tag|pin, value, expected_versions{}}
                                  → 항목별 성공/충돌 결과 배열 반환(부분 성공 허용, 각각 버전 생성)
```

### Version
```
GET    /handovers/{id}/versions?page=              목록(요약: version_no, type, 변경필드, 작성자, 시각)
GET    /handovers/{id}/versions/{no}               해당 버전 전체 스냅샷
GET    /handovers/{id}/versions/diff?from=&to=     필드별 diff + 장문 텍스트 word-diff ops
POST   /handovers/{id}/versions/{no}/restore       {change_reason, expected_version} → 새 버전 생성
GET    /handovers/{id}/timeline                    Version+Ack+Transfer+Task+Comment+Attachment 통합
```

### Acknowledgement
```
GET    /handovers/{id}/acknowledgements                    누가 어느 버전을 확인했는가
POST   /handovers/{id}/acknowledge      {note?}            현재 current_version_no로 확인 기록
POST   /acknowledgements/bulk           {handover_ids[]}   선택 항목 일괄 확인
GET    /acknowledgements/pending?scope=me                  미확인/재확인 목록 (Dashboard 배너)
```

### 댓글 / 첨부
```
GET    /handovers/{id}/comments      POST /handovers/{id}/comments   {body}
PATCH  /comments/{id}   DELETE /comments/{id}        (본문 Version 생성 안 함, Audit은 기록)
POST   /handovers/{id}/attachments   (multipart)      GET /attachments/{id}/download
DELETE /attachments/{id}
```

## 4. 교대 인수인계

```
GET    /shift-handovers/cockpit?shift_date=&shift_id=&area=   area 는 목록을 채울 영역(기본 new_in_shift).
                                     나머지 영역은 숫자만(9,999 까지 세고 넘으면 capped=true)
       → { new_in_shift[], in_progress[], need_ack[], planned_next[], important[], overdue[], counts{} }

GET    /shift-handovers/basket                       내 DRAFT 세션(없으면 자동 생성)
POST   /shift-handovers/basket/items    {handover_ids[], item_note?}
DELETE /shift-handovers/basket/items/{item_id}
PATCH  /shift-handovers/basket          {to_user_ids?[], to_shift_id?, summary_note, order[]}
GET    /shift-handovers/basket/carry-forward-candidates   직전 세션 미완료 항목(기본 선택 상태)
POST   /shift-handovers/basket/send     {to_user_ids?[], to_shift_id?, summary_note}
       인수자를 여러 명 고를 수 있다(비우면 Basket 에 골라 둔 사람). 생략 시 Basket 기준
       → 항목별 version_no_at_transfer 고정, 인수자 **각각** ack(PENDING) 생성, 알림, Audit(HANDOVER_TRANSFER)
       → 항목의 ack_state 는 인수자 전원 기준 — 한 명이라도 확인 안 했으면 PENDING

GET    /shift-handovers?shift_date=&from=&to=&status=      인계 이력
GET    /shift-handovers/{id}                               항목 + 확인 현황
POST   /shift-handovers/{id}/close                         전원 확인 시 수동 종료
```

## 5. Task / My Work / 일정

```
POST   /tasks/search        {q, status[], include_closed, assignee: me|all|unassigned|<id>,
                             company_id, handover_id, due: overdue|today|this_week|none, sort, page, size}
                             (인수인계 DSL 이 아니라 정해진 조건 — ASSUMPTIONS B-11)
GET    /tasks/board?assignee=me|all|<id>&company_id=   → {columns: {TODO, IN_PROGRESS, WAITING, DONE(14일)}, counts}
POST   /tasks               GET/PATCH/DELETE /tasks/{id}      (PATCH 는 expected_version 필수, 어긋나면 409)
POST   /tasks/{id}/checklists   PATCH /checklists/{id}   DELETE /checklists/{id}
GET/POST /tasks/{id}/comments     DELETE /task-comments/{id}   (본인 것 또는 MANAGER+)
PATCH  /tasks/{id}/move     {expected_version, status, after_id|null}  ← 보드 끌어놓기
                             (after_id = 바로 앞 카드, null = 맨 위. 상태가 바뀔 때만 Audit)
GET    /handovers/{id}/tasks   연결된 할일
POST   /handovers/{id}/tasks   Quick Add (비운 칸은 관계사·제목·내용 앞 500자·중요도로 채움)

GET    /my-work?bucket=all|today|overdue|this_week|upcoming|need_ack|waiting|done
               &source=all|task|handover|ack|schedule
       → {counts: {버킷별 건수}, items: [{kind: TASK|HANDOVER|ACK, ...}]}   (버킷 규칙 ASSUMPTIONS B-12)
       건수가 응답에 같이 오므로 /my-work/summary 는 두지 않는다.

GET    /calendar?start=&end=&layers=schedule,task,handover&mine=   (기간 ≤ 100일, 끝 미포함)
       → {events: [{key, kind: SCHEDULE|TASK|HANDOVER, id, title, start/end | day, all_day,
                    recurring, can_move, version_no, ...}], truncated}
       반복 일정은 기간 안의 회차로 펼쳐 온다(회차마다 key 가 다르다). 할일은 마감일, 인수인계는 수행일.
POST   /schedules           {title?, start_at, end_at?, is_all_day, event_type, owner_id?, company_id?,
                             handover_id?, task_id?, recurrence_rule?, color?}   (규칙 ASSUMPTIONS B-13)
GET    /schedules/{id}      PATCH /schedules/{id} (expected_version 필수)    DELETE /schedules/{id} {reason?}
PATCH  /schedules/{id}/move {expected_version, start_at, end_at?}   ← 달력 끌어놓기(길이 유지, Audit via=drag)
GET    /handovers/{id}/schedules      GET /tasks/{id}/schedules

## 5-1. 감사 · 설정 · 댓글 · 첨부 · 통계 (Phase 8, ASSUMPTIONS B-14)

```
GET    /audit/catalog                 행위(한국어 이름·묶음) · 기록된 대상 종류 · max_range_days(93)
POST   /audit/search   {start, end (필수, ≤93일), user_id?, username?, actions[]?, resource_type?,
                        resource_id?, client_ip?(앞부분), result?, order, page, size}   ANALYST 는 자기 행위만
POST   /audit/export   (같은 조건) → {download_token} → GET /export/download/{token}   (내보내기도 감사)
GET    /settings                      값 + spec(입력 형식·범위, 없으면 읽기 전용)
PATCH  /settings/{key} {value}        형식·범위 검사 후 저장(SETTING_CHANGE)
GET/POST /handovers/{id}/comments     PATCH/DELETE /handover-comments/{id}
GET    /attachments?entity_type=HANDOVER|TASK&entity_id=
POST   /attachments  (multipart: entity_type, entity_id, file)
GET    /attachments/{id}/download     (attachment; filename*=UTF-8'' · nosniff)     DELETE /attachments/{id}
GET    /attachments/{id}/preview      그림만(파일 내용으로 판단, 아니면 422)
                                      inline · nosniff · CSP — 받기와 달리 감사에 남기지 않는다
GET    /stats/summary?start=&end=     (MANAGER+, 기본 최근 30일, ≤366일)

GET    /credentials?scope=&company_id=&q=   장비 비밀번호 목록(공용 전부 + 내 개인 것, 값은 없음)
POST   /credentials                  {scope, company_id?, device_name, access_method?, username?, secret, note?}
GET    /credentials/{id}             PATCH(같은 필드 + change_note) · DELETE(소프트)
POST   /credentials/{id}/reveal      {password: 본인 계정 비밀번호} → {secret}
       비밀번호 값이 나가는 유일한 경로. 본인 확인 + CREDENTIAL_REVEAL 감사(실패는 ..._DENIED)
GET    /credentials/{id}/versions    변경 이력(값 없음, has_secret 로 옛 값 보유 여부만)
POST   /credentials/{id}/versions/{no}/reveal   {password} → 그때의 비밀번호(최근 5개까지 보관)
```
```

## 6. 검색 / 저장된 보기

```
POST   /search/global        {q, scope:[handover,task,schedule], limit ≤ 50}   ← Ctrl+K 팔레트 · /search 화면
       → {hits: [{type, id, title, snippet, company, date, matched: [걸린 칸]}], totals: {종류별 건수}}
       인수인계는 목록 검색과 같은 범위(제목·내용·비고·관계사·전달자·담당자·확인자·태그), 할일·일정은 제목·내용.
       matched 는 어느 칸에서 걸렸는지 — 이름·관계사·태그로만 걸리면 snippet 이 '확인자: 홍길동' 형태.
                             → 타입별 상위 N + 총 건수 (Ctrl+K 팔레트)
POST   /search/handovers     = POST /handovers/search (동일 DSL, 별칭)
GET    /search/facets?target=handover&field=&q=&limit=
POST   /search/feedback      {query, mode, rating, clicked_handover_id}

GET    /saved-views?target=handover           개인 + 공용
POST   /saved-views          {name, target, scope, state}
PATCH  /saved-views/{id}     DELETE /saved-views/{id}
POST   /saved-views/{id}/default
```

## 7. Excel Import / Export

```
POST   /import/jobs                (multipart file)        → {job_id, sheets[]}
GET    /import/jobs/{id}                                   상태/진행률 폴링
GET    /import/jobs/{id}/analyze                           Sheet별 행수·헤더 후보
POST   /import/jobs/{id}/mapping   {column_mapping, options}
POST   /import/jobs/{id}/stage                             staging 적재(비동기)
GET    /import/jobs/{id}/preview?sheet=&page=              매핑 결과 미리보기
POST   /import/jobs/{id}/validate                          검증(비동기)
GET    /import/jobs/{id}/errors?page=                      오류 목록
POST   /import/jobs/{id}/dedup                             fingerprint 중복 판정
GET    /import/jobs/{id}/duplicates?page=                  중복 의심 + 기존 건 비교
PATCH  /import/jobs/{id}/decisions {row_ids[], decision}   IMPORT/SKIP 선택
POST   /import/jobs/{id}/commit                            실제 반영(비동기)
GET    /import/jobs/{id}/report                            결과 요약
GET    /import/jobs/{id}/errors.xlsx                       실패행 Excel 다운로드
POST   /import/jobs/{id}/rollback  [ADMIN]                 job 단위 되돌리기(Soft Delete)

POST   /export/handovers   {dsl, columns[], format:xlsx|csv}   → {download_token} (Audit 기록)
GET    /export/download/{token}
POST   /export/audit       [MANAGER+]
```

## 8. 알림 / 감사 / 통계 / 설정

```
GET    /notifications?unread=true&page=      POST /notifications/{id}/read
POST   /notifications/read-all               GET /notifications/unread-count

POST   /audit/search        (DSL: 기간 필수)   [MANAGER+]
GET    /audit/actions                          Action 코드 목록(필터 UI용)
POST   /audit/system-event  [내부/스크립트]    BACKUP/RESTORE 등 기록

GET    /stats/dashboard                        KPI 6종 + 각 영역 상위 N
GET    /stats/handovers?group_by=company|status|month&from=&to=
GET    /stats/ack-compliance?from=&to=         확인율/지연 확인 통계

GET    /settings/features                      {attachment{allowed_ext, max_size_mb}, ack{reack_fields},
                                                export{max_rows}, page{}, database, database_warning}
GET    /settings           [ADMIN]             PATCH /settings/{key} [ADMIN]
GET    /admin/integrity-check [ADMIN]          버전 정합성/고아 레코드 점검
```

## 8-1. 열람 그룹 (1.3.0)

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/groups/mine` | `handover:read` | **내가 속한 그룹** — 글 쓸 때 공개 범위 선택지 |
| GET | `/groups` | `group:manage` | 그룹 목록 + 구성원 수 · 업무 수(**이름과 숫자만**, 제목은 주지 않는다) |
| POST | `/groups` | `group:manage` | 만들기. 이름 중복은 409 |
| PATCH | `/groups/{id}` | `group:manage` | 이름 · 설명 · 순서 · 사용여부. '미분류'는 중지할 수 없다(422) |
| GET | `/groups/{id}/members` | `group:manage` | 구성원 |
| GET/PUT | `/users/{id}/groups` | `group:manage` | 한 사람의 소속을 통째로 바꾼다 — **다음 요청부터** 적용(캐시 없음) |
| GET | `/groups/unclassified/summary` | `group:manage` | 미분류로 남은 자료(관계사별 건수) |
| POST | `/groups/unclassified/move` | `group:manage` | 지정 그룹으로 이관. **전체 공개로 바꾸지 않는다** |

업무 등록 · 수정에 `visibility`(`GROUPS`\|`ALL`)와 `group_ids` 가 더해졌다. 비우면
`GROUPS` + **쓴 사람의 기본 그룹**이 들어간다(전체 공개로 자동 넘어가지 않는다).
내가 속하지 않은 그룹에 공개하려 하면 422.

못 보는 업무는 **404** 로 답한다(403 이면 그 번호의 업무가 있다는 사실이 새어 나간다).
이미 발급된 Export 내려받기 토큰도, 발급 당시보다 소속이 좁아지면 404 로 거절한다.

---

## 8-2. 근무표 (1.3.0)

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/roster/teams` | `schedule:read` | 조 편성(구성원 포함) |
| PATCH | `/roster/teams/{id}` | `shift:manage` | 이름 · 주기 위치 · 사용여부 |
| PUT | `/roster/teams/{id}/members` | `shift:manage` | 편성 교체. 두 조 중복은 409 |
| GET | `/roster/calendar?view=week\|month&mine=` | `schedule:read` | 하루에 주간 · 야간 두 줄(계획 · 실제 · 결원) |
| GET | `/roster/day?work_date=` | `schedule:read` | 그 날 두 교대 |
| GET | `/roster/mine?days=` | `schedule:read` | 내 근무(대근으로 들어온 것 포함) |
| GET | `/roster/next-shift` | `schedule:read` | **다음 근무의 실제 근무자** — 인계 상대 추천 |
| GET | `/roster/coverage?start=&days=` | `schedule:read` | 매일 주간 1조 · 야간 1조인지 확인 |
| GET | `/roster/overrides` | `schedule:read` | 변경 이력(취소된 것도 보여 준다) |
| POST | `/roster/overrides` | `shift:manage` | 대근(`on_user_id` 있음) · 결원(없음) |
| POST | `/roster/swaps` | `shift:manage` | 맞교환 — 두 줄로 적고 서로를 가리킨다 |
| POST | `/roster/overrides/{id}/cancel` | `shift:manage` | 되돌리기(맞교환은 양쪽 함께) |
| POST | `/roster/epoch?value=YYYY-MM-DD` | `shift:manage` | 기준일. 주기가 안 맞물리면 **저장하지 않고** 422 |

같은 날(또는 바로 앞 야간) 근무에 이미 들어 있는 사람을 대근으로 넣으면 409.

---

## 8-2-1. 복수 담당 · 전파 · 분석 의뢰 (1.3.0)

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/handovers/{id}/participants` | `handover:read` | 대표 담당 · 공동 담당 · 필수 인수자 · 참고 + 역할별 수 |
| PUT | `/handovers/{id}/participants` | `handover:update_own` + 본인 건 | 통째로 바꾼다. **사람을 뺄 수 있어서** 본문 수정과 같은 자격 |
| POST | `/handovers/{id}/propagate/preview` | `handover:read` | 누르기 전에 — 담당 N / 필수 N / 참고 N / 제외 M |
| POST | `/handovers/{id}/propagate` | `handover:read` | 그룹 단위 전파. **더하기만** 하고 공개 범위는 바뀌지 않는다 |
| GET/POST | `/handovers/{id}/request` | `handover:read` | 분석 의뢰(받는 사람은 필수 인수자로 걸린다) |
| POST | `/handovers/{id}/request/accept` | `handover:read` | 접수 — 여기서부터 응답 시간이 재어진다 |
| POST | `/handovers/{id}/request/answer` | `handover:read` | 회신. **내용이 없으면 422** |

역할은 `OWNER`(대표 담당) · `CO_OWNER`(공동 담당) · `REQUIRED`(필수 인수자) · `FYI`(참고).
한 사람은 한 역할만 가지며, 같은 사람이 여럿 들어오면 **강한 역할**만 남는다. 확인(ack)
의무는 `FYI` 를 뺀 셋에 붙는다 — 참고로 보낸 사람이 미확인으로 잡히면 안 된다.

의뢰 상태는 `NONE → REQUESTED → ACCEPTED → ANSWERED`. 접수를 건너뛰고 바로 회신할 수
있지만(간단한 건은 보자마자 답한다) **되돌릴 수는 없다**. 회신한 건에 다시 의뢰하면
앞선 회신을 남긴 채 `REQUESTED` 로 돌아간다(추가 질문).

---

## 8-3. 교대 마감 점검 · 내 일정 · 일정 알림 (1.3.0)

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/shift-handovers/closing-check` | `shift:transfer` | 다섯 줄 — 확인하지 않은 인계 · 보내지 않은 바구니 · 내 담당 미완료 · 지연 · 다음 근무 결원. 각 줄에 `url` 이 붙어 **누르면 그 목록**이 열린다 |
| GET | `/schedules/mine?days=&per_series=` | `schedule:read` | 내 일정. 반복은 앞 N회차까지 + 가려진 회차 수 |
| PUT | `/schedules/{id}/reminder` | `schedule:read` | 내 알림. `null`=끄기 · `0`=시작 · `10`/`30`=N분 전 · 그 밖=직접 |

점검의 숫자는 목록과 **같은 검색 조건**(search_service)으로 센다 — '점검은 3건인데
목록은 2건'이 생기지 않는다. 알림은 기존 알림함으로 간다(새 통로를 만들지 않는다).

---

## 8-4. RAG 바닥 공사 (1.3.0 — 모델 없음)

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/rag/contract` | `handover:read` | 접근 계약 · 사례 문서의 칸 · 색인에 넣지 않는 자료 |
| GET | `/rag/verification-examples` | `handover:read` | 붙인 뒤 가장 먼저 확인할 질문과 지켜져야 할 것 |
| GET | `/rag/cases?limit=` | `export:run` | 사례 묶음(내가 볼 수 있는 범위) |
| POST | `/rag/cases` | `export:run` | 목록과 같은 검색 조건으로 사례를 뽑는다 |

자세한 내용은 [RAG.md](RAG.md). 모델 · 벡터 DB 는 없다.

---

## 8-5. 운영 지식 (1.3.1)

목록 · 상세 · 첨부 · 개정 이력이 **모두 같은 열람 판정**을 지난다. 볼 수 없는 문서는
번호를 알아도 404 다(있다는 사실도 알려 주지 않는다).

| Method | Path | 설명 |
|---|---|---|
| GET | `/knowledge` | 목록. `q`(제목·본문·태그) · `category` · `tag` · `review_due_only` · `include_deleted` · `offset` · `limit` |
| GET | `/knowledge/categories` | 분류 목록 |
| GET | `/knowledge/template` | 표준 양식(목적·범위 / 탐지·확인 / 분석 / 조치 / 보고·전파 / 후속 / 관련 문서) |
| GET | `/knowledge/suggest` | `text` 또는 `handover_id` 로 관련 절차 추천(규칙 기반 — AI 아님) |
| GET | `/knowledge/for-handover/{handover_id}` | 그 인계에 걸어 둔 절차 |
| POST | `/knowledge` | 등록. `visibility=GROUPS` 면 `group_ids` 필수(내가 속한 그룹만) |
| GET | `/knowledge/{id}` | 상세(삭제된 문서도 `is_deleted=true` 로 돌려준다 — 복원 화면에 필요) |
| PATCH | `/knowledge/{id}` | 수정. `version_no` 필수(동시 편집 덮어쓰기 방지) · `change_note` 는 이력에 남는다 |
| DELETE | `/knowledge/{id}` | 지운 표시(복원 가능) |
| POST | `/knowledge/{id}/restore` | 지운 문서 되살리기 |
| GET | `/knowledge/{id}/revisions` | 개정 이력 |
| GET | `/knowledge/{id}/revisions/{version_no}` | 그 판의 본문(두 번 불러 나란히 비교) |
| POST | `/knowledge/{id}/revisions/{version_no}/restore` | 옛 판 복원 — 지우지 않고 **새 판**으로 올린다 |
| GET | `/knowledge/{id}/handovers` | 연결된 인계. **읽는 사람이 볼 수 있는 것만** |
| POST | `/knowledge/{id}/handovers` | 연결(내가 볼 수 있는 인계만 걸 수 있다) |
| DELETE | `/knowledge/{id}/handovers/{handover_id}` | 연결 끊기(작성자·근무 관리자) |

첨부는 기존 `/attachments` 를 `entity_type=KNOWLEDGE` 로 쓴다. 읽기 권한은 문서를 그대로 상속한다.

감사: `KNOWLEDGE_CREATE` · `KNOWLEDGE_UPDATE` · `KNOWLEDGE_DELETE` · `KNOWLEDGE_RESTORE` · `KNOWLEDGE_LINK`
(UPDATE · DELETE 는 고위험 — 기록이 실패하면 업무도 되돌린다).

---

## 8-6. 공개 범위 — 저장 전 점검 · 과거 자료 전환 (1.3.1)

| Method | Path | 설명 |
|---|---|---|
| POST | `/groups/scope-check` | `{visibility, group_ids, user_ids}` → 그 범위로 올리면 **누가 못 보는가**. 아무것도 바꾸지 않는다 |
| GET | `/groups/public-migration` | 전환 대상 건수 · 미리보기 목록 · 경고 · 확인 문구 (`group:manage`) |
| GET | `/groups/public-migration/batches` | 전환 이력(묶음별 건수 · 승인자 · 되돌림 수) |
| POST | `/groups/public-migration/apply` | `{confirm, backup_confirmed}` — 문구가 틀리거나 백업 동의가 없으면 422 |
| POST | `/groups/public-migration/batches/{batch_id}/revert` | 묶음 단위 되돌리기 |

그룹 단위 전파에도 같은 경고가 있다 — `POST /handovers/{id}/propagate/preview` 응답의
`outside_scope` 는 그룹 제한 글을 그 그룹 밖으로 전파할 때만 채워진다(아니면 `null`).

`scope-check` 응답의 `outsiders` 는 지정 그룹에 속하지 않은 담당자·전파 대상이다.
**거절하지 않고 알린다** — 담당자는 그 일을 해야 하므로 글을 볼 수 있어야 하지만,
그룹 제한이 그 사람에게만 풀린다는 사실을 쓰는 사람이 알아야 한다.

감사: `SCOPE_PUBLIC_MIGRATE` · `SCOPE_PUBLIC_REVERT` (둘 다 고위험).

---

## 8-7. 비밀번호 금고 단기 열람 (1.3.1)

본인 인증 한 번으로 **자기가 볼 수 있는** 비밀번호를 제한 시간 동안 목록으로 본다.

| Method | Path | 설명 |
|---|---|---|
| POST | `/credentials/vault/unlock` | `{password}` → `{token, expires_in_seconds, remaining_absolute_seconds}` |
| GET | `/credentials/vault/status` | 남은 시간. 서버가 판정한다(화면 시계를 믿지 않는다) |
| GET | `/credentials/vault/secrets?ids=1&ids=2` | 지정 항목의 평문. 한 번에 200건까지(화면은 100건씩 나눠 부른다) |
| POST | `/credentials/vault/extend` | 5분 연장. 연속 유지 상한(기본·최대 15분)을 넘기지 못한다 |
| POST | `/credentials/vault/lock` | 지금 잠그기. 토큰이 없으면 그 사람의 세션을 모두 닫는다 |

- 토큰은 `X-Vault-Token` 헤더로 보낸다. 서버는 **요청 사용자 · 비밀번호 해시 · IP ·
  브라우저** 에 묶어 프로세스 메모리에만 둔다(DB · 쿠키에 쓰지 않는다).
- `scope=PERSONAL` 은 등록한 사람에게만. **남의 개인 비밀번호는 일괄 열람에도 404** 다.
- 로그아웃 · 비밀번호 변경/초기화 · 역할 변경 · 계정 비활성 · 그룹 소속 변경이 일어나면
  세션이 그 자리에서 끊긴다.
- `/api/v1/credentials` 아래 모든 응답에 `Cache-Control: no-store` (오류 응답 포함).
- 감사: `CREDENTIAL_VAULT_UNLOCK` · `_DENIED` · `_BATCH_REVEAL`(실제로 연 항목 번호) ·
  `_EXTEND` · `_LOCK`.

---

## 8-8. 정기 점검 (1.3.1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/schedules/inspections?day=YYYY-MM-DD` | 그 날 돌아야 하는 `INSPECTION` 반복 일정과 완료 여부 |
| POST | `/schedules/{id}/completions` | `{occurrence_date, note}` 로 그 회차 완료 |
| DELETE | `/schedules/{id}/completions/{day}` | 완료 되돌리기 |

점검은 **일정**으로 등록한다(`event_type=INSPECTION` + `recurrence_rule`). 새 메뉴를 두지
않은 이유는 MENU_MAP.md 에 적었다.

---

## 9. AI — 범위에서 제외

`/ai/*` 경로는 없다. AI 는 만들지 않기로 했다(ASSUMPTIONS E-01).

---

## 10. RBAC 매트릭스 (요약)

| 자원/행위 | ANALYST | MANAGER | ADMIN |
|---|---|---|---|
| 인수인계 조회/검색/Export | ✅ | ✅ | ✅ |
| 인수인계 생성 | ✅ | ✅ | ✅ |
| 인수인계 수정 | 본인 작성 또는 담당자 | 전체 | 전체 |
| 인수인계 삭제(Soft) | ❌ | ✅ | ✅ |
| 삭제 데이터 조회/복구 | ❌ | 조회만 | ✅ |
| 상단고정/중요 지정 | 본인 건만 중요 | ✅ | ✅ |
| 교대 인계 실행 | ✅ | ✅ | ✅ |
| 확인(ack) | 본인 | 본인 | 본인 |
| 공용 SavedView | ❌ | ✅ | ✅ |
| Excel Import | ❌ | ✅ | ✅ |
| Import Rollback | ❌ | ❌ | ✅ |
| Audit 조회 | 본인 이력만 | 전체 | 전체 |
| 사용자/역할 관리 | ❌ | ❌ | ✅ |
| 시스템 설정 | ❌ | ❌ | ✅ |
| 열람 그룹 관리(`group:manage`) | ❌ | ❌ | ✅ |
| **다른 그룹 업무 원문 열람** | ❌ | ❌ | ❌ — 역할로는 열리지 않는다 |
| 근무표 보기 | ✅ | ✅ | ✅ |
| 조 편성 · 대근 · 맞교환(`shift:manage`) | ❌ | ❌ | ✅ |
| RAG 사례 묶음(`export:run`) | ✅ | ✅ | ✅ — 내가 볼 수 있는 범위만 |
| 담당 · 전파 대상 바꾸기 | 본인 건 | 전체 | 전체 |
| 그룹 전파 · 분석 의뢰 · 접수 · 회신 | ✅ | ✅ | ✅ — 볼 수 있는 건에 한해 |

권한 체크는 라우터 데코레이터(`Depends(require("handover:update"))`) + 서비스 레이어의 소유권 검사 2단으로 수행한다.
