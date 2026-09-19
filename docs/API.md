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
GET    /handovers/{id}            상세 (+ ack 상태, tag, task/schedule/첨부 카운트)
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
GET    /shift-handovers/cockpit?shift_date=&shift_id=
       → { new_in_shift[], in_progress[], need_ack[], planned_next[], important[], overdue[], counts{} }

GET    /shift-handovers/basket                       내 DRAFT 세션(없으면 자동 생성)
POST   /shift-handovers/basket/items    {handover_ids[], item_note?}
DELETE /shift-handovers/basket/items/{item_id}
PATCH  /shift-handovers/basket          {to_user_id?, to_shift_id?, summary_note, order[]}
GET    /shift-handovers/basket/carry-forward-candidates   직전 세션 미완료 항목(기본 선택 상태)
POST   /shift-handovers/basket/send     {to_user_id|to_shift_id, summary_note}
       → 항목별 version_no_at_transfer 고정, ack(PENDING) 생성, 알림, Audit(HANDOVER_TRANSFER)

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

POST   /schedules/search    GET /schedules?from=&to=&type=&company_id=
POST   /schedules           PATCH /schedules/{id}     DELETE /schedules/{id}
PATCH  /schedules/{id}/move {start_at, end_at}        ← 달력 DnD (Audit 기록)
```

## 6. 검색 / 저장된 보기

```
POST   /search/global        {q, scope:[handover,task,schedule,attachment], limit}
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

GET    /settings/features                      {ai_enabled, ai_features{}, attachment{}, shift[]}
GET    /settings           [ADMIN]             PATCH /settings [ADMIN]
GET    /admin/integrity-check [ADMIN]          버전 정합성/고아 레코드 점검
```

## 9. AI (Optional — 비활성 시 404)

```
GET    /ai/status                    provider, model, healthy, enabled_features
POST   /ai/search     {question, filters?}
       → { answer, sources:[{handover_id, company, date, title, snippet, score}],
           used_filters:{...}, retrieval:{fts_hits, vector_hits}, latency_ms }
POST   /ai/summarize  {handover_ids[]}         (summary_enabled=true)
POST   /ai/suggest-tags {handover_id|text}     (tag_suggest_enabled=true)
POST   /ai/reindex    [ADMIN]                  (embedding_enabled=true)
GET    /ai/reindex/status
```

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
| 시스템 설정/AI 설정 | ❌ | ❌ | ✅ |

권한 체크는 라우터 데코레이터(`Depends(require("handover:update"))`) + 서비스 레이어의 소유권 검사 2단으로 수행한다.
