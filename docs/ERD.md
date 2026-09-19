# ERD.md — Database 설계

> 대상 DBMS: PostgreSQL 16 (운영) / SQLite (개발·테스트 전용)
> 모든 타임스탬프는 `TIMESTAMPTZ`, 애플리케이션 표준 시간대는 **Asia/Seoul**.
> 모든 테이블에 `created_at`, `updated_at` 기본 포함(명시 생략).

---

## 1. 관계 개요

```
users ──< handovers(creator/sender/assignee)        companies ──< handovers
  │                                                    │
  │         handovers ──1:N── handover_versions (append-only)
  │              │  ├──1:N── handover_acknowledgements ──> users
  │              │  ├──1:N── handover_comments
  │              │  ├──1:N── handover_tags ──> tags
  │              │  ├──1:N── attachments (polymorphic)
  │              │  ├──1:N── tasks
  │              │  ├──1:N── schedules
  │              │  ├──1:N── shift_handover_items ──> shift_handovers ──> shifts
  │              │  └──1:1── handover_embeddings (선택, pgvector)
  │
  ├──< tasks ──< task_checklists / task_comments
  ├──< schedules
  ├──< saved_views
  ├──< notifications
  ├──< audit_logs
  └──< handover_stars (개인 즐겨찾기)

excel_import_jobs ──< excel_import_rows ──< excel_import_errors
system_settings (key-value)      search_feedback
```

---

## 2. 계정 / 권한

### users
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| username | VARCHAR(64) UNIQUE NOT NULL | 로그인 ID |
| display_name | VARCHAR(100) NOT NULL | 화면 표기명(예: 홍길동) |
| email | VARCHAR(200) NULL | |
| password_hash | VARCHAR(255) NULL | Argon2id. 외부 인증 사용자면 NULL |
| auth_provider | VARCHAR(20) NOT NULL DEFAULT 'local' | local / ldap / ad |
| external_id | VARCHAR(200) NULL | LDAP DN 등 |
| role_code | VARCHAR(20) FK roles.code NOT NULL | ADMIN / MANAGER / ANALYST |
| team | VARCHAR(50) NULL | 소속 조(A조/B조 등) |
| phone | VARCHAR(30) NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT true | |
| must_change_password | BOOLEAN NOT NULL DEFAULT false | 초기 관리자 계정용 |
| failed_login_count | SMALLINT NOT NULL DEFAULT 0 | |
| locked_until | TIMESTAMPTZ NULL | Brute force 방어 |
| last_login_at | TIMESTAMPTZ NULL | |

INDEX: `(is_active, display_name)`, UNIQUE `(auth_provider, external_id)`

### roles
`code PK (ADMIN|MANAGER|ANALYST)`, `name`, `description`, `sort_order`
※ 개별 권한(permission)은 코드의 RBAC 매트릭스(`auth/rbac.py`)로 관리한다. DB에 권한 행을 두면 감사·리뷰가 어려워지고, 본 시스템의 역할 수가 3개로 고정적이기 때문. 역할 추가가 필요해지면 `role_permissions` 테이블로 승격한다.

### refresh_tokens
`id PK`, `user_id FK`, `token_hash UNIQUE`, `issued_at`, `expires_at`, `revoked_at`, `client_ip`, `user_agent`
→ 로그아웃/강제 만료/세션 목록 제공. 토큰 원문은 저장하지 않는다(SHA-256 해시).

### login_attempts
`id PK`, `username`, `client_ip`, `success BOOLEAN`, `attempted_at`, `reason`
INDEX `(username, attempted_at DESC)`, `(client_ip, attempted_at DESC)`

---

## 3. 기준 정보

### companies (관계사)
`id PK`, `code VARCHAR(30) UNIQUE`, `name VARCHAR(100) NOT NULL UNIQUE`, `short_name`, `color VARCHAR(7)`, `is_active`, `sort_order`, `note`
INDEX `(is_active, sort_order, name)`

### handover_statuses (§19, 관리자 편집 가능)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| code | VARCHAR(20) PK | NEW, IN_PROGRESS, NEED_CHECK, ACTION_PLANNED, WAITING, HOLD, DONE, CANCELED |
| name | VARCHAR(30) NOT NULL | 신규, 진행중, 확인필요, 조치예정, 대기, 보류, 완료, 취소 |
| category | VARCHAR(20) NOT NULL | OPEN / WAITING / CLOSED — **Carry Forward·미완료 판정의 기준** |
| color | VARCHAR(7) | |
| icon | VARCHAR(30) | 색상 단독 의존 금지 |
| sort_order | SMALLINT | |
| is_active | BOOLEAN | |
| is_system | BOOLEAN | 시스템 기본값은 삭제 불가(비활성만 가능) |

### priorities (§20)
`code PK (URGENT|HIGH|NORMAL|LOW)`, `name(긴급/높음/보통/낮음)`, `level SMALLINT(0=최상)`, `color`, `icon`, `is_active`

### shifts (§27)
`id PK`, `code VARCHAR(20) UNIQUE(DAY|NIGHT, 구 SWING 은 비활성)`, `name`, `start_time TIME`, `end_time TIME`, `crosses_midnight BOOLEAN`, `sort_order`, `is_active`

### tags
`id PK`, `name VARCHAR(50) UNIQUE`, `color`, `usage_count INT DEFAULT 0`, `created_by`
INDEX `gin (name gin_trgm_ops)` — 태그 자동완성

---

## 4. 인수인계 (핵심)

### handovers — 현재 상태 스냅샷 + 검색 대상
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | 화면 표기 `#18234` |
| company_id | BIGINT FK companies NOT NULL | |
| title | VARCHAR(300) NOT NULL | |
| content | TEXT NOT NULL | 상세내용 |
| remark | TEXT NULL | 비고 |
| status_code | VARCHAR(20) FK handover_statuses NOT NULL | |
| priority_code | VARCHAR(20) FK priorities NOT NULL DEFAULT 'NORMAL' | |
| registered_date | DATE NOT NULL | 등록일(원본 Excel '날짜') |
| work_date | DATE NULL | 수행(예정)일 |
| completed_at | TIMESTAMPTZ NULL | 완료일시 |
| sender_id | BIGINT FK users NULL | 전달자 |
| sender_name_raw | VARCHAR(100) NULL | 원본 표기 보존(Import 무손실) |
| assignee_id | BIGINT FK users NULL | 담당자 |
| assignee_name_raw | VARCHAR(100) NULL | |
| checker_id | BIGINT FK users NULL | 확인자(원본 Excel '확인자') |
| checker_name_raw | VARCHAR(100) NULL | |
| is_important | BOOLEAN NOT NULL DEFAULT false | 중요여부 |
| is_pinned | BOOLEAN NOT NULL DEFAULT false | 상단고정(전역) |
| is_recurring | BOOLEAN NOT NULL DEFAULT false | 반복업무 |
| current_version_no | INT NOT NULL DEFAULT 1 | Optimistic Lock 키 |
| ack_state_cache | VARCHAR(20) NOT NULL DEFAULT 'NONE' | **집계** 확인상태(비정규화). 규칙: 하나라도 REACK_REQUIRED → REACK_REQUIRED, 아니면 하나라도 PENDING → PENDING, ack가 전부 ACKED → ACKED, ack row 없음 → NONE. "확인 필요" 목록 필터의 1차 축소용 |
| last_transferred_at | TIMESTAMPTZ NULL | |
| carry_count | SMALLINT NOT NULL DEFAULT 0 | 몇 교대째 인계 중인가 |
| source_file | VARCHAR(255) NULL | Import 추적 |
| source_sheet | VARCHAR(100) NULL | |
| source_row | INT NULL | |
| import_job_id | BIGINT FK excel_import_jobs NULL | |
| fingerprint | CHAR(64) NULL | 중복검사 해시 |
| created_by / updated_by | BIGINT FK users | |
| is_deleted | BOOLEAN NOT NULL DEFAULT false | Soft Delete |
| deleted_at / deleted_by / delete_reason | | |
| search_text | TEXT | 제목+내용+비고+관계사+인명+태그 concat (트리거 유지) |
| search_tsv | TSVECTOR | `to_tsvector('simple', search_text)` (트리거 유지) |

**인덱스 (§75, 실제 질의 패턴 기준으로만 생성)**
```sql
-- 기본 목록: 최신순 + 미삭제
CREATE INDEX ix_ho_list          ON handovers (is_deleted, registered_date DESC, id DESC);
-- 관계사별 기간 조회 (가장 흔한 복합조건)
CREATE INDEX ix_ho_company_date  ON handovers (company_id, registered_date DESC) WHERE is_deleted = false;
-- 미완료 업무 스캔 (Cockpit / Carry Forward)
CREATE INDEX ix_ho_open          ON handovers (status_code, work_date) WHERE is_deleted = false;
-- 내 업무
CREATE INDEX ix_ho_assignee      ON handovers (assignee_id, status_code, work_date) WHERE is_deleted = false;
CREATE INDEX ix_ho_sender        ON handovers (sender_id, registered_date DESC) WHERE is_deleted = false;
-- 중요/고정
CREATE INDEX ix_ho_important     ON handovers (is_pinned DESC, is_important DESC, registered_date DESC)
                                  WHERE is_deleted = false AND (is_pinned OR is_important);
-- 확인 필요
CREATE INDEX ix_ho_ack           ON handovers (ack_state_cache) WHERE is_deleted = false AND ack_state_cache <> 'ACKED';
-- 검색
CREATE INDEX ix_ho_tsv           ON handovers USING gin (search_tsv);
CREATE INDEX ix_ho_trgm          ON handovers USING gin (search_text gin_trgm_ops);
-- 중복 검사
CREATE INDEX ix_ho_fingerprint   ON handovers (fingerprint);
CREATE INDEX ix_ho_import        ON handovers (import_job_id);
```
> 불필요한 단일 컬럼 인덱스(priority_code 단독 등)는 만들지 않는다. 카디널리티가 낮아 부분 인덱스나 복합 인덱스의 후행 컬럼으로 충분하다.

### handover_versions — append-only
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| handover_id | BIGINT FK NOT NULL | |
| version_no | INT NOT NULL | UNIQUE(handover_id, version_no) |
| change_type | VARCHAR(20) NOT NULL | CREATE / UPDATE / STATUS / RESTORE / DELETE / UNDELETE / IMPORT |
| before_data | JSONB NULL | **변경된 필드의 변경 전 값만** |
| after_data | JSONB NOT NULL | **변경 후 전체 스냅샷** (단독 복원 가능) |
| changed_fields | TEXT[] NOT NULL | |
| change_reason | TEXT NULL | RESTORE/DELETE 시 필수 |
| restored_from_version | INT NULL | |
| changed_by | BIGINT FK users NOT NULL | |
| changed_at | TIMESTAMPTZ NOT NULL | |
| client_ip | INET NULL | |
| user_agent | VARCHAR(400) NULL | |

INDEX: `(handover_id, version_no DESC)`, `(changed_by, changed_at DESC)`, `(changed_at DESC)`
※ UPDATE/DELETE 금지(애플리케이션 규칙 + DB 권한 분리 권장). 연 단위 파티셔닝은 500만행 초과 시 검토.

### handover_acknowledgements — "누가 어느 버전을 확인했는가"
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| handover_id | BIGINT FK NOT NULL | UNIQUE(handover_id, user_id) |
| user_id | BIGINT FK users NOT NULL | |
| state | VARCHAR(20) NOT NULL | PENDING / ACKED / REACK_REQUIRED |
| acked_version_no | INT NULL | 확인 당시 current_version_no |
| acked_at | TIMESTAMPTZ NULL | |
| required_by_session_id | BIGINT FK shift_handovers NULL | 어떤 인계로 인해 확인 의무가 생겼는가 |
| stale_since | TIMESTAMPTZ NULL | 재확인 필요로 바뀐 시각 |
| stale_reason | TEXT[] NULL | 변경된 필드 목록 |
| note | TEXT NULL | 확인 코멘트 |

INDEX: `(user_id, state)`, `(handover_id, state)`

> **목록의 "확인상태" 컬럼은 로그인 사용자 기준**이다.
> `LEFT JOIN handover_acknowledgements a ON a.handover_id = h.id AND a.user_id = :me` 로 내 상태(`✔ v5` / `⚠ 재확인` / `○ 대기` / `-`)를 표시하고,
> `handovers.ack_state_cache`(집계값)는 "확인 필요" 필터가 큰 테이블을 먼저 줄이는 용도로만 쓴다.
> 두 값은 의미가 다르므로 화면에서 혼용하지 않는다(내 상태 = 행 표시, 집계 = 필터/Cockpit 카운트).

### handover_stars (개인 즐겨찾기 ★)
`user_id + handover_id PK`, `created_at`
※ 전역 `is_pinned`와 구분. ★ 컬럼은 로그인 사용자 기준으로 LEFT JOIN 1회.

### handover_comments (§65 — 본문 Version과 분리)
`id PK`, `handover_id FK`, `author_id FK`, `body TEXT`, `is_edited`, `edited_at`, `is_deleted`, `deleted_at`, `deleted_by`
INDEX `(handover_id, created_at)`

### handover_tags
`handover_id + tag_id PK`

### handover_embeddings (선택, AI ON)
`handover_id PK FK`, `model VARCHAR(100)`, `embedding vector(768)`, `source_hash CHAR(64)`, `updated_at`
INDEX: `USING hnsw (embedding vector_cosine_ops)` — pgvector 설치 시에만 생성(Alembic 조건부).

---

## 5. 교대 인수인계

### shift_handovers (세션)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| shift_date | DATE NOT NULL | 근무일(야간은 시작일 기준) |
| shift_id | BIGINT FK shifts NOT NULL | 인계하는 쪽 근무 |
| to_shift_id | BIGINT FK shifts NULL | 인수 근무 |
| from_user_id | BIGINT FK users NOT NULL | |
| to_user_id | BIGINT FK users NULL | 개인 지정 인계 |
| status | VARCHAR(20) NOT NULL | DRAFT / SENT / CLOSED |
| sent_at | TIMESTAMPTZ NULL | |
| closed_at | TIMESTAMPTZ NULL | 전 항목 확인 완료 시각 |
| summary_note | TEXT NULL | 교대 총평 |
| item_count / acked_count | INT | 캐시 |

INDEX: `(shift_date DESC, shift_id)`, `(to_user_id, status)`, `(from_user_id, status)`
UNIQUE: `(from_user_id, status)` WHERE status='DRAFT' — 사용자당 Basket 1개

### shift_handover_items
`id PK`, `session_id FK`, `handover_id FK`, `version_no_at_transfer INT NULL`(SENT 시 고정), `item_note TEXT`, `display_order SMALLINT`, `carried_from_item_id BIGINT NULL`, `is_carry_forward BOOLEAN`
UNIQUE `(session_id, handover_id)` / INDEX `(handover_id, id DESC)`

---

## 6. Task / 일정

### tasks
`id PK`, `handover_id FK NULL`, `company_id FK NULL`, `title VARCHAR(300)`, `description TEXT`,
`status VARCHAR(20)` (TODO/IN_PROGRESS/WAITING/DONE/CANCELED), `priority_code FK`,
`assignee_id FK`, `creator_id FK`, `start_date DATE`, `due_date DATE`, `completed_at`,
`board_order INT`, `is_deleted`, `deleted_at/by`
INDEX: `(assignee_id, status, due_date)`, `(handover_id)`, `(due_date) WHERE status NOT IN ('DONE','CANCELED')`

### task_checklists
`id PK`, `task_id FK`, `title VARCHAR(200)`, `is_done`, `done_at`, `done_by`, `sort_order`

### task_comments
`id PK`, `task_id FK`, `author_id FK`, `body TEXT`, `is_deleted`

### schedules
`id PK`, `title`, `description`, `event_type VARCHAR(20)` (GENERAL/WORK_PLANNED/INSPECTION/MEETING/SECURITY_WORK/RECURRING),
`start_at TIMESTAMPTZ`, `end_at TIMESTAMPTZ`, `is_all_day BOOLEAN`,
`company_id FK NULL`, `handover_id FK NULL`, `task_id FK NULL`, `owner_id FK`,
`recurrence_rule VARCHAR(200) NULL` (RFC5545 RRULE 부분집합), `color`, `is_deleted`
INDEX: `(start_at, end_at)`, `(owner_id, start_at)`, `(handover_id)`, `(task_id)`

---

## 7. 공통 / 운영

### attachments (polymorphic)
`id PK`, `entity_type VARCHAR(20)` (HANDOVER/TASK), `entity_id BIGINT`, `original_name VARCHAR(255)`,
`stored_name VARCHAR(100)` (UUID+ext), `rel_path VARCHAR(300)`, `mime VARCHAR(100)`, `size_bytes BIGINT`,
`sha256 CHAR(64)`, `scan_status VARCHAR(20) DEFAULT 'NOT_SCANNED'`, `uploaded_by`, `uploaded_at`, `is_deleted`
INDEX `(entity_type, entity_id)`

### saved_views (§15)
| 컬럼 | 비고 |
|---|---|
| id PK / name / description | |
| scope VARCHAR(10) | PERSONAL / SHARED (SHARED는 MANAGER+ 생성) |
| owner_id FK NULL | SHARED면 생성자 |
| target VARCHAR(20) | HANDOVER / TASK / AUDIT / SCHEDULE |
| state JSONB NOT NULL | `{filters, q, sort, group, visible_columns, column_order, column_width, row_density, view_type, page_size}` |
| is_default BOOLEAN | 사용자 기본 보기 |
| sort_order / created_by / updated_at | |

UNIQUE `(scope, owner_id, target, name)` / INDEX `(target, scope, owner_id)`

### notifications (§66)
`id PK`, `user_id FK`, `type VARCHAR(40)` (HANDOVER_ASSIGNED / ACK_REQUIRED / CHANGED_AFTER_TRANSFER / TASK_ASSIGNED / TASK_DUE_SOON / TASK_OVERDUE / IMPORTANT_HANDOVER),
`title`, `body`, `link_type`, `link_id`, `is_read`, `read_at`, `created_at`, `dedup_key VARCHAR(120)`
INDEX `(user_id, is_read, created_at DESC)`, UNIQUE `(user_id, dedup_key)` WHERE is_read=false — 알림 폭주 방지

### audit_logs (§61)
| 컬럼 | 타입 |
|---|---|
| id BIGSERIAL PK / event_uuid UUID UNIQUE | |
| occurred_at TIMESTAMPTZ NOT NULL | |
| user_id BIGINT NULL / username VARCHAR(64) / role_code VARCHAR(20) | 사용자 삭제되어도 증적 보존(비정규화) |
| client_ip INET / user_agent VARCHAR(400) / request_id VARCHAR(40) | |
| action VARCHAR(40) NOT NULL | §60 목록 |
| resource_type VARCHAR(30) / resource_id VARCHAR(50) | |
| before_value JSONB / after_value JSONB | 요약(민감/대용량 필드는 길이 제한) |
| result VARCHAR(10) NOT NULL | SUCCESS / FAILURE |
| error_message TEXT NULL | |
| detail JSONB NULL | 필터 조건, 건수 등 |

INDEX: `(occurred_at DESC)`, `(user_id, occurred_at DESC)`, `(action, occurred_at DESC)`, `(resource_type, resource_id)`
※ 조회는 기간 필수(무제한 스캔 금지). 월 단위 파티셔닝은 500만행 초과 시.

### excel_import_jobs
`id PK`, `job_code VARCHAR(40) UNIQUE` (IMPORT-20260916-001), `file_name`, `stored_path`, `file_sha256`,
`status VARCHAR(20)` (UPLOADED/ANALYZED/MAPPED/STAGED/VALIDATED/DEDUPED/RUNNING/COMPLETED/FAILED/ROLLED_BACK),
`sheet_summary JSONB`, `column_mapping JSONB`, `options JSONB`,
`total_rows / success_rows / duplicate_rows / error_rows / skipped_rows INT`,
`started_at / finished_at / created_by`, `error_message`

### excel_import_rows (staging)
`id PK`, `job_id FK`, `sheet_name`, `source_row INT`, `raw JSONB`, `normalized JSONB`,
`fingerprint CHAR(64)`, `dup_type VARCHAR(20)` (NONE/IN_BATCH/EXISTING), `dup_handover_id BIGINT NULL`,
`decision VARCHAR(20)` (PENDING/IMPORT/SKIP), `status VARCHAR(20)` (STAGED/VALID/INVALID/IMPORTED/FAILED), `handover_id BIGINT NULL`
INDEX `(job_id, status)`, `(job_id, fingerprint)`

### excel_import_errors
`id PK`, `job_id FK`, `row_id FK NULL`, `sheet_name`, `source_row`, `column_name`, `error_code`, `message`, `raw_value`

### system_settings
`key VARCHAR(100) PK`, `value JSONB NOT NULL`, `value_type VARCHAR(20)`, `category VARCHAR(30)`,
`description`, `is_secret BOOLEAN`, `updated_by`, `updated_at`
기본 키 예: `ack.reack_fields`, `ai.search_enabled`, `attachment.allowed_ext`, `attachment.max_size_mb`,
`shift.definitions`, `export.max_rows`, `retention.audit_days`
※ `is_secret=true` 값은 API 응답에서 마스킹, API Key는 DB가 아니라 `.env`에만 둔다.

### search_feedback
`id PK`, `user_id`, `query TEXT`, `mode VARCHAR(20)` (GRID/FTS/AI), `result_count`, `clicked_handover_id`, `rating SMALLINT`, `comment`, `created_at`

---

## 8. 무결성 / 정합성 규칙

1. `handovers.current_version_no` 는 반드시 `MAX(handover_versions.version_no)` 와 일치 (정합성 점검 API `/admin/integrity-check` 제공).
2. `handover_versions` 는 INSERT만 허용. 운영 DB에서는 앱 계정에 UPDATE/DELETE 권한을 부여하지 않는 것을 권장.
3. Soft Delete된 Handover는 모든 일반 질의에서 제외(리포지토리 기본 필터). ADMIN만 `include_deleted=true` 사용 가능.
4. `handover_statuses.category='CLOSED'` 인 상태만 완료로 간주(Carry Forward·My Work·지연 판정의 단일 기준).
5. 사용자 삭제는 비활성화(`is_active=false`)로만 수행. audit_logs·versions의 이름 컬럼은 비정규화되어 있어 증적이 남는다.
6. 첨부 파일 실제 삭제는 Soft Delete 후 보존기간 경과 시 배치로만. 삭제도 Audit.
