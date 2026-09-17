# ARCHITECTURE.md — SOC Handover Platform

> 문서 버전: 1.0 (Phase 0) / 2026-09-16

---

## 1. 핵심 Domain 정의

### 1.1 Bounded Context

| Context | 책임 | 주요 Entity |
|---|---|---|
| **Continuity** (연속성) | 인수인계 사실의 기록·버전·교대 전달·확인 | Handover, HandoverVersion, Acknowledgement, Shift, ShiftHandover, ShiftHandoverItem |
| **Work** (실행) | 실제 수행할 액션과 일정 | Task, TaskChecklist, TaskComment, Schedule |
| **Discovery** (탐색) | 찾기. 필터·검색·저장된 보기·AI | SearchQuery(DSL), SavedView, SearchFeedback, Embedding |
| **Governance** (통제) | 누가 무엇을 했는가, 권한, 설정 | AuditLog, User, Role, SystemSetting, Notification |
| **Migration** (이관) | Excel → DB | ExcelImportJob, ExcelImportRow, ExcelImportError |

### 1.2 개념 구분 (가장 중요)

```
Handover  = "알아야 하는 사실/상황/진행"      (사실 기록, 버전 관리 대상)
Task      = "해야 하는 행동"                  (실행 관리 대상, 상태/마감/담당)
Schedule  = "언제 일어나는 일"                (시간축)
Ack       = "특정 Version을 특정 사용자가 확인했다는 증적"
Transfer  = "특정 시각에 A가 B에게 이 항목들을 넘겼다는 증적"
```

Handover 1 : N Task, Handover 1 : N Schedule, Task 1 : N Schedule.
**Handover를 Task로 대체하지 않는다.** 하나의 Handover가 0개의 Task를 가질 수 있다(단순 공유 사실).

### 1.3 Aggregate 경계

- `Handover`가 Aggregate Root. Version·Ack·Tag·Attachment·Comment는 Handover를 통해서만 일관성 보장.
- `ShiftHandover`(세션)가 Root. Item은 세션을 통해서만 생성/삭제.
- `Task`는 독립 Root(Handover 없이도 존재 가능). Checklist/Comment는 Task 하위.

---

## 2. 전체 시스템 Architecture

### 2.1 배치 (Windows 단일 노드)

```
┌────────────────────── Windows 10 / 11 PC (사내 내부망) ──────────────────────┐
│                                                                              │
│  Chrome / Edge                                                               │
│      │  http://<host>:8080                                                   │
│      ▼                                                                       │
│  ┌──────────────────────── Uvicorn (FastAPI, :8080) ────────────────────┐   │
│  │  /            → StaticFiles (frontend/dist, SPA fallback)            │   │
│  │  /api/*       → REST API                                             │   │
│  │  /api/docs    → OpenAPI (ADMIN 전용, 운영 시 비활성 가능)             │   │
│  │                                                                      │   │
│  │  [Middleware] RequestContext(req_id, ip, ua) → Auth → RBAC →         │   │
│  │               RateLimit → AuditContext → ErrorHandler                │   │
│  │                                                                      │   │
│  │  [API Layer]        라우터. 입출력 스키마 변환만.                      │   │
│  │  [Service Layer]    트랜잭션 경계. 버전 생성·ack 무효화·감사 기록.     │   │
│  │  [Repository Layer] SQLAlchemy 질의. 필터 DSL → SQL 컴파일.           │   │
│  │  [Model Layer]      SQLAlchemy ORM + Alembic 마이그레이션             │   │
│  │                                                                      │   │
│  │  [Background] APScheduler in-process                                 │   │
│  │      · Excel Import Worker (job queue, DB 기반)                       │   │
│  │      · Embedding Worker (AI ON일 때만)                                │   │
│  │      · Notification/Carry-Forward 스윕 (교대 시각 기준)                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│      │                         │                          │                  │
│      ▼                         ▼                          ▼                  │
│  PostgreSQL 16            data/attachments/          (선택) Ollama :11434    │
│  (+pg_trgm, 선택 pgvector)  data/imports/             또는 사내 OpenAI 호환   │
│                             data/backup/                                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **단일 포트 운영**: 운영 모드에서는 FastAPI가 빌드된 프론트 정적 파일을 직접 서빙한다. 리버스 프록시·Docker 불필요.
- **개발 모드**: Vite dev server(5173) + `/api` proxy → 8080.
- **프로세스 관리**: `start.ps1`이 uvicorn을 백그라운드 프로세스로 띄우고 PID를 `run/app.pid`에 기록. `stop.ps1`이 종료. 선택적으로 NSSM 기반 Windows 서비스 등록 스크립트 제공.

### 2.2 Backend 모듈 구조

```
backend/
└─ app/
   ├─ main.py               # FastAPI 앱 조립만 (라우터 등록, 미들웨어, static)
   ├─ core/
   │   ├─ config.py         # pydantic-settings. .env 로드. Secret 하드코딩 금지
   │   ├─ db.py             # Engine/Session, dialect 감지
   │   ├─ security.py       # 해시, 토큰, CSRF
   │   ├─ context.py        # RequestContext (user, ip, ua, request_id)
   │   ├─ errors.py         # 예외 → RFC7807 응답
   │   ├─ pagination.py     # offset/keyset 공통
   │   └─ time.py           # 근무일/교대 계산 유틸 (KST 고정)
   ├─ models/               # ORM (파일당 1~2 aggregate)
   ├─ schemas/              # Pydantic I/O
   ├─ api/v1/               # 라우터: auth, users, companies, handovers, versions,
   │                        #         acks, shifts, shift_handovers, tasks, schedules,
   │                        #         search, saved_views, imports, exports,
   │                        #         notifications, audit, settings, ai, stats
   ├─ services/             # 도메인 로직 (handover_service, version_service,
   │                        #  ack_service, shift_service, carry_forward, task_service,
   │                        #  import_service, export_service, notification_service)
   ├─ repositories/         # 질의 전담 (handover_repo, search_repo, facet_repo, audit_repo)
   ├─ search/
   │   ├─ dsl.py            # 필터 DSL 정의/검증
   │   ├─ compiler.py       # DSL → SQLAlchemy 조건
   │   ├─ fields.py         # 화이트리스트 필드 레지스트리 (SQLi 방어의 핵심)
   │   └─ backends/         # postgres.py (tsvector+trgm), sqlite.py (FTS5+LIKE)
   ├─ auth/
   │   ├─ providers/        # local.py, (확장) ldap.py
   │   ├─ rbac.py           # 권한 매트릭스, Depends(require("handover:update"))
   │   └─ deps.py
   ├─ importers/excel/      # reader(openpyxl read_only), mapper, validator,
   │                        # fingerprint, duplicate, runner
   ├─ audit/                # recorder.py (서비스에서 호출), decorators.py
   ├─ llm/
   │   ├─ base.py           # LLMProvider Protocol
   │   ├─ providers/        # disabled.py, ollama.py, openai_compatible.py
   │   ├─ rag/              # query_analyzer, retriever(hybrid), ranker(RRF), answerer
   │   └─ embedding/        # embedder, store(pgvector | 미사용)
   ├─ jobs/                 # APScheduler 등록, import worker, embed worker, sweeps
   ├─ utils/
   └─ tests/                # unit / api / e2e / perf
```

**규칙**: `main.py` 100줄 이내. 라우터 파일 300줄 이내. 서비스 함수 하나가 1 트랜잭션.
API 레이어는 DB 세션에 직접 질의하지 않는다. Repository는 비즈니스 규칙을 모른다.

### 2.3 Frontend 모듈 구조

```
frontend/src/
├─ app/                  # QueryClient, Router, Theme, ErrorBoundary
├─ layouts/              # AppShell(Sidebar+Topbar), AuthLayout
├─ routes/               # 라우트 정의 (lazy import)
├─ components/ui/        # shadcn/ui 기반 프리미티브
├─ components/grid/      # DataGrid 공통 (TanStack Table + 가상스크롤)
│                        #  ColumnFilterPopover / TextFilter / DateFilter / ValueFilter
│                        #  FilterChips / DensityToggle / ColumnManager / Paginator
├─ features/
│   ├─ handover/         # list, drawer(tabs), form, version-diff, timeline
│   ├─ shift/            # cockpit, basket, transfer, ack
│   ├─ task/             # list, board, detail, checklist
│   ├─ calendar/
│   ├─ search/           # global search, advanced, saved view
│   ├─ importer/         # 8-step wizard
│   ├─ audit/
│   ├─ admin/            # users, settings, statuses, companies
│   └─ ai/               # AI 검색 (설정 ON일 때만 라우트 등록)
├─ hooks/                # useQueryState(URL 동기화), useHotkeys, useMe
├─ services/api/         # 타입 안전 API 클라이언트 (도메인별 파일)
├─ stores/               # zustand: gridState, basketStore, uiStore
└─ types/                # 백엔드 스키마와 1:1 대응 타입
```

**규칙**: 컴포넌트 300줄 초과 시 분할. 그리드 상태는 URL query string에 직렬화(공유·새로고침 보존).

---

## 3. Handover Version 설계 (§21~§26)

### 3.1 저장 전략

```
handovers            ← 현재 상태(조회·검색·정렬 대상) + current_version_no
handover_versions    ← append-only 스냅샷 (수정 금지, 삭제 금지)
```

- **`after_data` = 변경 후 전체 스냅샷(JSONB)**: 어느 버전이든 단독으로 복원·표시 가능. JOIN 없이 특정 시점 재현.
- **`before_data` = 변경된 필드의 변경 전 값만(JSONB)**: 저장량 2배 증가 방지. 전체 이전 상태는 `version_no - 1`의 `after_data`가 그대로 제공하므로 정보 손실 없음.
- 목록 조회는 `handovers`만 읽는다. **버전 테이블을 JOIN하지 않는다.**

### 3.2 쓰기 경로 (Update)

```
1. BEGIN
2. SELECT ... FROM handovers WHERE id=:id FOR UPDATE          -- 행 잠금(짧게)
3. if payload.expected_version != row.current_version_no:
       ROLLBACK → 409 CONFLICT {current_version, current_data, my_diff}
4. changed = diff(current_snapshot, new_snapshot)             -- 값 동일 필드는 제외
   if not changed: return 200 (no-op, 버전 생성 안 함)
5. INSERT handover_versions(version_no = current+1,
        change_type, before_data=changed.before, after_data=new_snapshot,
        changed_fields, change_reason, changed_by, changed_at, client_ip, user_agent)
6. UPDATE handovers SET <fields>, current_version_no = current+1,
        updated_at, updated_by, search_tsv = to_tsvector(...)
7. if changed_fields ∩ REACK_FIELDS:                          -- 설정값
        UPDATE handover_acknowledgements
           SET state='REACK_REQUIRED', stale_since=now(), stale_reason=changed_fields
         WHERE handover_id=:id AND state='ACKED'
        → Notification 생성(확인자 전원)
8. INSERT audit_logs(action='HANDOVER_UPDATE', before/after 요약)
9. COMMIT
```

- `version_no`는 `UNIQUE(handover_id, version_no)`로 보장. 경합 시 재시도 1회.
- **생성(Create)도 v1 버전 레코드를 만든다**(change_type=CREATE, before_data=null).
- 상태 변경, 담당자 지정 같은 단일 필드 변경도 동일 경로를 탄다(별도 UPDATE 금지).

### 3.3 Diff / 복원

- Diff API: `GET /handovers/{id}/versions/diff?from=3&to=4` → 필드별 `{field, label, before, after, type}`.
  장문 텍스트는 서버에서 토큰 단위 diff(difflib) 계산 결과(`ops: [equal|insert|delete]`)를 함께 반환 → 프론트는 렌더만.
- 복원: `POST /handovers/{id}/versions/{n}/restore` → v(n) 의 `after_data`를 새 버전 v(current+1)로 기록.
  `change_type=RESTORE`, `restored_from_version=n`, `change_reason` 필수 입력.
  **기존 버전은 절대 덮어쓰지 않는다.**

### 3.4 동시성 UX

409 응답 본문:
```json
{ "error":"version_conflict", "current_version":6, "your_version":5,
  "conflicting_fields":["status","content"],
  "current": { ...현재 스냅샷... }, "yours": { ...내 입력... } }
```
프론트는 "다른 사용자가 수정했습니다 / [최신 내용 보기] [내 변경내용 비교]" 다이얼로그를 띄운다. 자동 병합·자동 덮어쓰기 없음.

---

## 4. Shift Handover 설계 (§27~§34)

### 4.1 모델

```
shifts               DAY(08:00-16:00) / SWING(16:00-00:00) / NIGHT(00:00-08:00)
                     crosses_midnight 플래그, 관리자 편집 가능

shift_handovers      (세션) shift_date, shift_id, from_user_id, to_user_id | to_shift_id,
                     status: DRAFT → SENT → (CLOSED), sent_at, note, ack_summary

shift_handover_items handover_id, version_no_at_transfer(스냅샷 고정),
                     item_note, carried_from_item_id, display_order

handover_acknowledgements
                     handover_id, user_id, acked_version_no, acked_at,
                     state: PENDING | ACKED | REACK_REQUIRED,
                     source_session_id, stale_since, stale_reason
```

### 4.2 흐름

```
[근무 중] Cockpit에서 6개 영역 확인
   → 항목 선택 → [인계 대상에 추가]  ... DRAFT 세션(자동 생성)에 item 추가
   → Basket 패널에서 순서/메모 정리
   → [다음 근무자에게 인계] 실행
        · 각 item에 현재 version_no를 **고정 기록** (전달 당시 내용이 무엇이었는지 증적)
        · 수신자에 대해 ack row(PENDING) 생성
        · Notification 발송, Audit(HANDOVER_TRANSFER) 기록
        · 세션 SENT
[다음 근무자 로그인]
   → "⚠ 확인하지 않은 인수인계 N건" 배너
   → 항목 확인 → ack.state=ACKED, acked_version_no = 확인 시점 current_version_no
      (전달 시 버전이 아니라 **확인 시점 버전**을 기록해야 "확인 이후 변경"을 판단할 수 있다)
[인계 후 수정 발생]
   → 재확인 대상 필드 변경 → ack.state=REACK_REQUIRED + 알림
   → UI: "현재 v7 / 김철수 확인 v5 / ⚠ 확인 이후 내용 변경됨 · 재확인 필요"
```

### 4.3 Carry Forward (복제 금지)

- 다음 교대 Basket 구성 시, **직전 세션 item 중 `handover.status`가 종결(완료/취소)이 아닌 것**을 자동 후보로 제시하고 기본 선택 상태로 둔다.
- 새 세션의 item에 `carried_from_item_id`를 연결 → "이 업무는 3교대째 인계 중" 표시(`carry_count` 계산).
- 데이터 복제 없음. 동일 `handover_id`를 계속 참조.
- 자동 스윕: 교대 시각에 미완료 + 미인계 항목이 있으면 관리자에게 "인계 누락 가능" 알림(누락 방지 2차 안전망).

---

## 5. Search Architecture (§50~§51, §8~§14)

### 5.1 계층

```
① Column Filter (구조화 DSL)     ← 기본이자 가장 중요
② Quick Filter (미리 정의된 DSL 프리셋)
③ Global Search (q=) : FTS + trigram
④ Saved View (DSL + 그리드 상태 저장)
⑤ Advanced Search (AND/OR 그룹, 필드 지정)
⑥ Full Text Search 전용 화면
⑦ AI Natural Language (선택) → 최종적으로 ①~⑥의 DSL로 변환되어 실행
```
**AI는 검색의 우회로가 아니라 ①~⑥ 위의 얇은 껍데기다.**

### 5.2 Filter DSL

```jsonc
{
  "q": "DDoS",                       // global search (선택)
  "filters": [                       // 서로 AND
    {"field":"company_id","op":"in","value":[1,3]},
    {"field":"work_date","op":"between","value":["2026-08-01","2026-08-31"]},
    {"field":"status_code","op":"in","value":["IN_PROGRESS"]},
    {"field":"content","op":"contains","value":"DDoS"},
    {"field":"assignee_id","op":"is_null"}
  ],
  "sort": [{"field":"work_date","dir":"desc"},{"field":"priority","dir":"asc"}],
  "page": 1, "size": 50,
  "cursor": null                     // 깊은 페이지용 keyset (선택)
}
```

- 연산자: `in, not_in, eq, ne, contains, not_contains, starts_with, ends_with, between, gte, lte, is_null, is_not_null, any_of_tags`
- **필드는 `search/fields.py`의 화이트리스트에만 존재.** 사용자 입력 문자열이 SQL 식별자로 흘러가지 않는다(SQLi 원천 차단).
- 날짜 Quick Filter는 프론트가 `between`으로 변환(서버 타임존 KST 고정, `TODAY/THIS_WEEK/...` 심볼도 서버가 해석 가능).

### 5.3 한글 Full Text 전략 (핵심 판단)

PostgreSQL 기본 설치에는 한국어 형태소 사전이 없다. 사내망/오프라인 환경에서 `mecab-ko` 빌드를 강제하는 것은 운영 리스크가 크다. 따라서:

| 계층 | 수단 | 인덱스 |
|---|---|---|
| 정확/부분 일치 (한글 조사 문제 해결) | `pg_trgm` 의 `ILIKE '%term%'` / `similarity()` | `GIN (search_text gin_trgm_ops)` |
| 토큰 기반 랭킹 (영문·숫자·IP·장비명에 강함) | `to_tsvector('simple', ...)` + `websearch_to_tsquery` | `GIN (search_tsv)` |
| 결합 | `WHERE tsv @@ q OR search_text ILIKE ...` → `ts_rank + similarity` 가중합 | |

- `search_text` = 제목+내용+비고+관계사명+인명+태그를 concat한 생성 컬럼(또는 트리거 유지).
- 2글자 이하 질의는 trigram이 비효율 → `ILIKE 'term%'` prefix 경로로 전환.
- `pg_trgm`은 contrib 기본 포함이라 추가 설치가 사실상 불필요(설치 스크립트가 `CREATE EXTENSION` 시도, 실패 시 LIKE fallback으로 degrade하고 경고).
- 형태소 분석기는 **나중에 교체 가능한 지점**으로 격리(`search/backends/postgres.py` 한 곳).

### 5.4 Facet(값 목록) 조회

`GET /search/facets?field=company_id&q=A&limit=50&filters=<현재 필터>` → `[{value,label,count}]`
- 현재 적용된 다른 필터를 반영한 건수(Excel 자동필터 체감과 동일).
- 카디널리티가 큰 필드(담당자·태그)는 `q` 서버 검색 + 상위 N + "더 보기".

### 5.5 대용량 페이징

- 기본: offset 페이징 + `count(*) OVER ()` 대신 **분리 count 쿼리**(동일 조건, 필요 시 근사치 캐시).
- 100페이지 초과 등 깊은 페이지: `cursor`(정렬키+id 복합 keyset)로 자동 전환.
- 전체 건수는 필터 없을 때 `pg_class.reltuples` 근사치 사용 가능(“전체 135,382건” 표시용), 검색결과 건수는 정확 count.

---

## 6. Excel Migration Architecture (§44~§48)

### 6.1 파이프라인

```
UPLOAD          파일 저장(data/imports/<job_id>/), 확장자·크기·매직바이트 검증
  ↓
ANALYZE         openpyxl read_only=True 로 Sheet별 행수·헤더 후보 추출 (메모리 상수)
  ↓
MAP             컬럼 매핑 제안(문자열 유사도) → 사용자 확정. 미매핑 컬럼은 raw_extra에 보존
  ↓
STAGE           excel_import_rows 에 원본 그대로 적재 (raw JSONB + source_row)
  ↓
VALIDATE        타입/필수/날짜파싱/길이/관계사·사용자 매칭 → excel_import_errors
  ↓
DEDUP           fingerprint = sha256(norm(company)|norm(date)|norm(content)|norm(sender))
                · 배치 내 중복 / 기존 DB 중복 표시. **자동 삭제 없음**
  ↓
COMMIT          사용자가 선택한 행만 chunk(500) 단위 INSERT + v1 version + audit(1건 요약)
  ↓
REPORT          성공/중복의심/실패 + 오류 Excel 다운로드 + 롤백(job 단위) 옵션
```

### 6.2 설계 결정

- **Staging 필수**: 검증·중복판정 결과를 사용자에게 보여주고 선택하게 하려면 중간 저장소가 있어야 한다. 바로 INSERT 금지(§46).
- **비동기 Job**: 수십만 행은 HTTP 요청 수명 안에서 처리 불가. `excel_import_jobs.status`를 폴링(`GET /import/jobs/{id}`)하고 진행률 표시.
- **Import 시 버전**: 마이그레이션 행도 v1 버전을 남긴다(`change_type=IMPORT`, `change_reason='Excel Import <job>'`). 감사 일관성 유지.
- **Audit 폭증 방지**: 행 단위 audit 대신 job 단위 1건 + 통계. 행 추적은 `excel_import_rows`가 담당.
- **관계사/사용자 자동 생성**: 기본 OFF. 매핑되지 않는 값은 "미등록" 경고 후 사용자가 (a) 신규 생성 (b) 기존 매핑 (c) 문자열 보존 중 선택.
  → Excel 인명은 표기 흔들림이 크므로 `sender_name_raw`/`assignee_name_raw` 텍스트 컬럼을 항상 보존하고, 매핑된 `*_id`는 별도로 둔다. **원본 무손실.**

### 6.3 Export

- `POST /export/handovers` 는 **목록 화면과 동일한 DSL**을 받는다 → 화면 결과 = Export 결과 보장.
- 5만행 초과 시 스트리밍(xlsxwriter constant_memory) + 다운로드 토큰. Audit(EXCEL_EXPORT)에 필터 조건 JSON 기록.

---

## 7. My Work / Task Architecture (§35~§41)

### 7.1 통합 질의

My Work는 별도 테이블을 만들지 않고 4개 소스를 UNION하는 **Work Item View**로 구성한다.

```sql
-- 개념 (실제는 SQLAlchemy로 구성, 각 소스에 LIMIT 후 병합)
SELECT 'HANDOVER' src, id, title, due(work_date), status, priority, ... WHERE assignee_id=:me AND NOT closed
UNION ALL
SELECT 'ACK'      src, h.id, ...                WHERE ack.user_id=:me AND ack.state IN ('PENDING','REACK_REQUIRED')
UNION ALL
SELECT 'TASK'     src, t.id, ..., due_date      WHERE t.assignee_id=:me AND NOT closed
UNION ALL
SELECT 'SCHEDULE' src, s.id, ..., start_at      WHERE s.owner_id=:me AND s.start_at >= today
```

버킷 분류(서버 계산):
`OVERDUE(due < today & !done)`, `TODAY(due = today)`, `THIS_WEEK`, `UPCOMING`, `WAITING(대기/보류/ack대기)`, `DONE`.

### 7.2 Task 상태

`TODO / IN_PROGRESS / WAITING / DONE / CANCELED` (Kanban 컬럼과 1:1). Handover 상태와 **분리**(혼동 방지).
Task 완료가 Handover 완료를 자동 트리거하지 않는다. 다만 Handover Drawer에 `완료 2/5` 진행률을 표시하고, 전부 완료 시 "인수인계도 완료 처리할까요?" 제안만 한다.

---

## 8. LLM Optional Architecture (§52~§57)

### 8.1 스위치

```
LLM_PROVIDER = disabled | ollama | openai_compatible     (.env)
LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_EMBED_MODEL    (.env, 하드코딩 금지)
system_settings: ai.search_enabled / ai.embedding_enabled / ai.summary_enabled / ai.tag_suggest_enabled  (기본 false)
```
`GET /api/v1/settings/features` 가 프론트에 `ai_enabled`를 내려주고, false면 AI 라우트·메뉴를 **등록하지 않는다**.
백엔드도 AI 라우터에서 `Depends(require_ai_enabled)` → 비활성 시 404.

### 8.2 Provider Adapter

```python
class LLMProvider(Protocol):
    async def health(self) -> ProviderHealth: ...
    async def chat(self, messages, *, temperature, max_tokens, timeout) -> ChatResult: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```
`DisabledProvider`는 모든 호출에 `FeatureDisabledError`. 팩토리는 설정만 보고 주입 → 도메인 코드에 provider 분기 없음.

### 8.3 Hybrid RAG

```
질문 → QueryAnalyzer (①규칙 기반 우선: 기간·관계사·상태·담당자·키워드 추출
                       ②LLM 보조: 실패 시에도 ①결과로 동작)
     → 구조화 필터(DSL)로 후보 축소  ← 메타데이터 필터가 1차 (정확도의 핵심)
     → FTS 랭킹(top 50) + Vector 랭킹(top 50, embedding ON일 때만)
     → RRF(Reciprocal Rank Fusion) 병합 + 최신성/중요도 가중
     → top 8 컨텍스트 → LLM 답변 생성(인용 ID 강제 포맷)
     → 응답 검증: 인용된 handover_id가 실제 후보에 없으면 제거.
       남은 근거 0건이면 "관련 인수인계를 찾지 못했습니다" 반환 (추측 금지)
```
- Embedding OFF여도 FTS 단독으로 RAG 동작(품질만 저하).
- pgvector 미설치 시 embedding 기능 자동 비활성 + 관리자 화면에 사유 표시.
- 답변은 항상 `sources: [{handover_id, company, date, title}]` 동반. 프론트는 클릭 시 Drawer로 이동.
- `search_feedback` 테이블에 👍/👎 수집 → 추후 랭킹 튜닝 근거.

---

## 9. Windows Deployment Architecture (§2, §82)

```
soc-handover/
├─ install.ps1     전제조건 점검(Python3.12/Node20+/PostgreSQL), venv 생성, 의존성 설치,
│                  .env 생성(관리자 비밀번호 **대화식 입력**), DB 생성 + alembic upgrade head,
│                  extension 생성 시도, 프론트 빌드
├─ start.ps1       .env 로드 → uvicorn 기동(백그라운드) → run/app.pid 기록 → 헬스체크 → URL 안내
├─ stop.ps1        pid 기반 정상 종료 (없으면 포트 기준 탐색)
├─ status.ps1      프로세스/포트/DB 연결/마이그레이션 리비전/디스크/최근 백업 요약
├─ backup.ps1      pg_dump -Fc → backup/soc_handover_<ts>.dump (+ attachments zip), 보존정책 N일
├─ restore.ps1     대상 dump 선택 → 확인 프롬프트 → pg_restore --clean
├─ .env.example
├─ backend/  frontend/  docs/  data/  backup/  run/  logs/
└─ docker-compose.yml   (선택 제공. 필수 아님)
```

- 모든 스크립트는 `-WhatIf` 유사 확인 프롬프트 및 실패 시 명확한 한국어 메시지.
- backup/restore 실행은 API를 통해 Audit에 기록(스크립트가 `/api/v1/audit/system-event` 호출, 실패해도 백업 자체는 진행).
- PostgreSQL 미설치 환경 대응은 `ASSUMPTIONS.md` A-01 참조(개발/평가용 SQLite fallback + 운영 경고).

---

## 10. Phase 구현 계획 (§86)

| Phase | 산출물 | 완료 판정(§87) |
|---|---|---|
| 0 | 설계 7문서 | 문서 리뷰 + 모순 점검 완료 ✅ |
| 1 | FastAPI+PG+Alembic+Auth+RBAC+AppShell+PS스크립트 | 로그인/권한/레이아웃 실동작, `status.ps1` OK, 테스트 통과 |
| 2 | Handover CRUD + Version + Diff + Restore + Optimistic Lock | 시나리오 B 백엔드 통과 |
| 3 | DataGrid + Column/Quick/Global Filter + SavedView + FTS | 시나리오 C 통과, 10만건 성능 측정 |
| 4 | Import Wizard 8단계 + Dedup + Export | 시나리오 A 통과, 5,000행×N sheet 실측 |
| 5 | Shift Cockpit + Basket + Transfer + Ack + Re-ack + Carry Forward | 시나리오 E 통과 |
| 6 | Task + Checklist + My Work + Board | 시나리오 D 통과 |
| 7 | Calendar + 연계 | 일정 CRUD/드래그 Audit 확인 |
| 8 | Audit UI + Admin + Notification + Backup/Restore | Audit 30종 기록 검증 |
| 9 | LLM Adapter + Hybrid RAG + Citation (Optional) | AI OFF/ON 양쪽 회귀 통과 |
| 10 | 성능/보안/E2E/패키징/문서 | 50만건 성능, E2E 5종, Windows 클린설치 |

각 Phase 종료 시 §87의 8항목(구현 기능 / 파일 / 테스트 결과 / 실패 테스트 / Windows 실행 확인 / 알려진 문제 / 남은 작업 / 다음 Phase)을 보고한다.

---

## 11. 예상 기술적 위험요소

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| R-01 | PostgreSQL 미설치/설치 권한 없음 | 운영 불가 | install.ps1 자동 점검 + 포터블 PG 안내 + 개발용 SQLite fallback(운영 경고 상시 노출) |
| R-02 | 한글 형태소 사전 부재로 FTS 품질 저하 | 검색 만족도 | trigram 병행(§5.3), 검색 백엔드 격리로 추후 교체 |
| R-03 | 50만건 + 복합필터 + 정렬 시 느린 count | 목록 지연 | 분리 count, 근사 total, keyset 페이징, 복합 인덱스 |
| R-04 | Excel 원본 품질(병합셀·날짜 문자열·인명 표기 흔들림) | Import 실패율 | 원본 raw 보존 + 관대한 파서 + 실패행 리포트 + 재시도 |
| R-05 | 버전 테이블 비대(JSONB 2벌) | 디스크 | before_data는 변경필드만, TOAST 압축, 연 단위 파티셔닝 검토 |
| R-06 | 동시 수정 충돌 빈발 | 사용성 저하 | 필드 단위 충돌 판정(같은 필드 아니면 병합 제안), Drawer 실시간 stale 배지 |
| R-07 | 알림/재확인 폭주 | 알림 피로 | 재확인 트리거 필드를 설정화, 동일 handover 알림 병합 |
| R-08 | OneDrive 동기화 폴더에서 node_modules/DB 파일 충돌 | 빌드 오류·동기화 지연 | `.gitignore`/OneDrive 제외 안내, data/ 는 로컬 경로 권장 |
| R-09 | AI 응답 지연·환각 | 신뢰 저하 | 타임아웃·스트리밍·근거 검증·근거 없으면 답변 거부 |
| R-10 | 단일 노드 장애 | 업무 중단 | 일 1회 자동 백업 + restore 리허설 문서화 + 읽기 전용 Export 백업 |

---

## 12. 개선 제안 (요구사항에 없으나 목적상 권장)

| # | 제안 | 근거 |
|---|---|---|
| P-01 | **"인계 누락 감지" 스윕** — 교대 종료 시점에 미완료·미인계 항목을 관리자에게 경고 | 1순위(누락 방지)의 2차 안전망 |
| P-02 | **Ack 만료(SLA)** — PENDING이 1교대 이상 방치되면 에스컬레이션 알림 | 확인 지연도 누락이다 |
| P-03 | **중복/유사 인수인계 추천** — 신규 등록 시 trigram 유사 과거 건 3개 제시 | "과거 사례 있었어?"를 AI 없이 해결 |
| P-04 | **읽기 전용 스냅샷 Export(주간 PDF/Excel)** | 감사·보고 대응, 시스템 장애 시 대체 열람 |
| P-05 | **Handover 템플릿** (DDoS/장애/점검 유형별 기본 항목) | 기재 누락 방지, 품질 균질화 |
| P-06 | **개인 컬럼 프로필 자동 저장** (마지막 그리드 상태 복원) | Excel 사용감에 근접 |
| P-07 | **감사용 "특정 시각 상태 재현" API** (`?as_of=2026-08-01T09:00`) | §89 "변경 전 내용 재현" 요구를 1급 기능으로 승격 |
| P-08 | **키보드 우선 조작** (j/k 이동, Enter 열기, e 수정, a 확인) | SOC 반복업무 속도 |
