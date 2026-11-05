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
  │              │  └──1:N── shift_handover_items ──> shift_handovers ──> shifts
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

---

## 4-1. 장비 비밀번호 보관

### credentials
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| scope | VARCHAR(10) NOT NULL | SHARED(교대 근무자 전원) / PERSONAL(등록자만) |
| owner_id | BIGINT FK users NOT NULL | 등록한 사람 — 고치기 · 지우기는 이 사람과 MANAGER+ |
| company_id | BIGINT FK companies NULL | 관계사 |
| device_name | VARCHAR(200) NOT NULL | 장비명 |
| access_method | TEXT NULL | 접속 방법(SSH 10.0.0.1:22 · 웹 · 콘솔) |
| username | VARCHAR(200) NULL | 계정 |
| secret_cipher | BYTEA NOT NULL | **AES-256-GCM 암호문**(키버전 1B + nonce 12B + 본문) |
| note | TEXT NULL | |
| rotated_at / rotated_by | TIMESTAMPTZ / BIGINT FK users | 비밀번호를 마지막으로 바꾼 때 · 사람 |
| current_version_no | INT NOT NULL | |
| is_deleted | BOOLEAN NOT NULL | |

INDEX: `(scope, owner_id, is_deleted)`, `(device_name)`, `(company_id)`

### credential_versions
`id PK`, `credential_id FK CASCADE`, `version_no INT`, `secret_cipher BYTEA NULL`(오래되면 값만 지움),
`changed_fields JSONB`, `changed_by FK users`, `change_note TEXT`, `device_name`, `username`, `key_version SMALLINT`
INDEX `(credential_id, version_no)`

평문 비밀번호는 DB 어디에도 없다. 키는 `.env`(VAULT_KEY)에 있고, 열람은 본인 확인 + 감사 기록을 거친다
(docs/SECURITY.md §7.1).

---

## 4-2. 열람 그룹 (1.3.0)

역할(roles)은 '무엇을 할 수 있는가'이고, 그룹은 '무엇을 **볼** 수 있는가'다. 둘을 한 테이블에
섞지 않는 이유: 관리자는 그룹을 만들고 사람을 넣을 수 있어야 하지만, 그 권한이 다른 그룹
업무의 원문을 읽는 근거가 되어서는 안 된다(열람 판정에 role 을 쓰지 않는다).

### groups
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| code | VARCHAR(30) UNIQUE NULL | 예약 그룹만 값이 있다(`UNCLASSIFIED`). 사람이 만든 그룹은 NULL |
| name | VARCHAR(60) UNIQUE NOT NULL | 현장 이름 그대로('관제1팀' · 'CERT') |
| description | TEXT NULL | |
| is_active | BOOLEAN NOT NULL | false 면 **즉시** 열람 판정에서 빠진다(멤버십을 지우지 않아도) |
| sort_order | SMALLINT NOT NULL | |

INDEX: `(is_active, sort_order)`

### user_groups
`id PK`, `user_id FK users CASCADE`, `group_id FK groups CASCADE`, `is_default BOOLEAN`
UNIQUE `(user_id, group_id)` · INDEX `(user_id)`, `(group_id)`

한 사람이 여러 그룹에 속할 수 있고, 그중 하나가 **기본 그룹**이다(새 글의 공개 범위 기본값).

### handover_groups
`id PK`, `handover_id FK handovers CASCADE`, `group_id FK groups CASCADE`
UNIQUE `(handover_id, group_id)` · INDEX `(group_id)`

### handovers.visibility
`VARCHAR(20) NOT NULL DEFAULT 'GROUPS'` — `GROUPS`(handover_groups 에 적힌 그룹만) ·
`ALL`(로그인한 모든 사람). 전체 공개는 **쓴 사람이 손으로 고를 때만** 된다.

열람 판정은 `group_service.visible_clause()` 한 곳에서 만든다(OR 네 가지):
전체 공개 · 내 활성 그룹 · 내가 당사자(작성·전달·담당·확인) · 교대 인계 수신자.
마지막 두 개가 없으면 그룹이 바뀌는 순간 내 담당 업무가 내 화면에서 사라진다.

**이관(마이그레이션 c8a2f4e7b015)**: 기존 자료를 전체 공개로 바꾸지 않는다. '미분류'
그룹 하나를 만들어 기존 업무 전부와 기존 사용자 전부를 넣는다 — 보이는 것은 그대로지만,
자료는 '모두에게 열린 것'이 아니라 '한 그룹에 속한 것'이 된다.

---

## 4-2-1. 업무에 걸린 사람 · 분석 의뢰 (1.3.0)

`handovers.assignee_id` 하나로는 모자란다. 침해사고 한 건에는 **손대는 사람 / 꼭 확인해야
하는 사람 / 알고만 있으면 되는 사람**이 섞인다. 구분하지 않으면 참고로 보낸 사람까지
미확인으로 잡혀 숫자가 늘 빨갛게 남는다.

### handover_participants
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| handover_id | BIGINT FK handovers CASCADE | |
| user_id | BIGINT FK users CASCADE | |
| role | VARCHAR(10) NOT NULL | OWNER(대표 담당) · CO_OWNER(공동) · REQUIRED(필수 인수자) · FYI(참고) |
| note | TEXT NULL | 왜 걸렸는지. 전파로 들어온 사람은 그 묶음 이름 |
| added_by | BIGINT FK users NULL | |

UNIQUE `(handover_id, user_id)` — **한 사람은 한 역할만**. 두 줄이 남으면 확인 숫자가 두 번
세어지고 알림이 두 번 간다. 전파에서 같은 사람이 두 역할로 들어오면 강한 쪽만 남긴다
(OWNER > CO_OWNER > REQUIRED > FYI).
INDEX: `(user_id, role)`, `(handover_id, role)`

확인(ack) 의무는 `FYI` 를 뺀 셋에 붙는다. 대표 담당(OWNER)은 `handovers.assignee_id` 와
같은 사람으로 맞춘다 — 두 곳이 어긋나면 목록의 '담당자'와 상세의 '대표 담당'이 다른
이름을 보여 준다.

**열람**: 걸린 사람은 그룹과 무관하게 그 건을 본다(`group_service.visible_clause`).
전파는 글의 `visibility` · 공개 그룹을 **바꾸지 않는다** — 사람을 거는 것이지 글을 여는
것이 아니다.

### handovers 의 분석 의뢰 칸
`request_state VARCHAR(12) NOT NULL DEFAULT 'NONE'` — NONE → REQUESTED → ACCEPTED → ANSWERED.
`requested_at/by` · `accepted_at/by` · `answered_at/by` · `request_note` · `answer_note`.
INDEX `(request_state, registered_date)`.

별도 테이블을 두지 않은 이유: 한 업무에 흐름이 하나뿐이고, 목록에서 '의뢰 중인 건'을
거르려면 같은 행에 있어야 한다. 되돌리기는 없다 — 상태 이력이 지워지면 '언제 맡겼고
언제 답이 왔는가'를 따질 근거가 사라진다.

**이관(f6d2b8a4c137)**: 담당자가 있는 기존 건은 그 사람이 **대표 담당**으로 들어간다.
보이는 것이 달라지지 않고, 공동 담당·필수 인수자를 더할 자리만 생긴다.

---

## 4-3. 근무표 (1.3.0)

4조 2교대는 **16일 주기로 완전히 되풀이**된다('주주주주' + '야비비'×4). 그래서 날짜마다
행을 깔지 않고 조마다 주기 위치만 적어 계산한다. 1년치를 행으로 만들면 365×4행이 되고,
기준일 하나를 고치는 순간 전부 다시 만들어야 한다.

### roster_teams
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| code | VARCHAR(10) UNIQUE NOT NULL | A · B · C · D |
| name | VARCHAR(40) NOT NULL | 1조 · 2조 … |
| phase_days | SMALLINT NOT NULL | 기준일에서 이 조가 주기의 몇 번째 날인가(4조면 0 · 4 · 8 · 12) |
| is_active | BOOLEAN NOT NULL | |
| sort_order | SMALLINT NOT NULL | |

### roster_members
`id PK`, `team_id FK roster_teams CASCADE`, `user_id FK users CASCADE`, `is_leader BOOLEAN`,
`sort_order SMALLINT` · UNIQUE `(team_id, user_id)` · INDEX `(user_id)`

한 사람이 두 조에 들어가는 것은 서버가 409 로 막는다.

### roster_overrides — 달라지는 것만 예외로
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | BIGSERIAL PK | |
| work_date | DATE NOT NULL | 야간은 **시작 날짜**(11/05 야간 = 11/05 18:00 ~ 11/06 09:00) |
| shift_code | VARCHAR(10) NOT NULL | DAY · NIGHT |
| kind | VARCHAR(10) NOT NULL | SUB(대근) · SWAP(맞교환) · OFF(결원) |
| off_user_id | BIGINT FK users NOT NULL | 빠지는 사람 |
| on_user_id | BIGINT FK users NULL | 들어오는 사람. 결원이면 NULL |
| pair_id | BIGINT FK roster_overrides NULL | 맞교환의 반대쪽 — 한쪽을 취소하면 함께 취소된다 |
| reason / cancel_reason | TEXT NULL | |
| canceled_at / canceled_by | TIMESTAMPTZ / BIGINT FK users | **지우지 않고 취소로 적는다**(이력) |

INDEX: `(work_date, shift_code)`, `(off_user_id, work_date)`, `(on_user_id, work_date)`

설정 `roster.epoch_date`(기준일) · `roster.team_size`(정원). 기준일을 바꿀 때는 32일치
'매일 주간 1조 · 야간 1조'를 확인하고, 맞물리지 않으면 **저장하지 않는다**.

---

## 4-4. 일정 알림 (1.3.0)

### schedule_reminders
`id PK`, `schedule_id FK schedules CASCADE`, `user_id FK users CASCADE`,
`minutes_before INT NULL` · UNIQUE `(schedule_id, user_id)` · INDEX `(user_id)`

`NULL`=끄기 · `0`=시작할 때 · `10`/`30`=N분 전 · 그 밖=직접 넣은 분.
일정 테이블에 컬럼으로 넣지 않은 이유: 일정은 여러 사람이 보지만 알림은 개인 설정이다 —
한 사람이 끈 것이 모두에게 적용되면 안 된다.

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
| status | VARCHAR(20) NOT NULL | DRAFT / SENT / CLOSED |
| sent_at | TIMESTAMPTZ NULL | |
| closed_at | TIMESTAMPTZ NULL | 전 항목 확인 완료 시각 |
| summary_note | TEXT NULL | 교대 총평 |
| item_count / acked_count | INT | 캐시 |

INDEX: `(shift_date DESC, shift_id)`, `(from_user_id, status)`
UNIQUE: `(from_user_id, status)` WHERE status='DRAFT' — 사용자당 Basket 1개

### shift_handover_recipients (인수자)
`id PK`, `session_id FK shift_handovers ON DELETE CASCADE`, `user_id FK users NOT NULL`, `display_order SMALLINT`(고른 순서)
UNIQUE `(session_id, user_id)` / INDEX `(user_id, session_id)`

인계 하나를 여러 명이 받을 수 있다. 확인(handover_acknowledgements)은 사람마다 따로 만들어지고,
항목이 확인된 것으로 보려면 인수자 **전원**이 확인해야 한다.

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
기본 키 예: `ack.reack_fields`, `attachment.allowed_ext`, `attachment.max_size_mb`,
`shift.definitions`, `export.max_rows`, `retention.audit_days`
※ `is_secret=true` 값은 API 응답에서 마스킹, API Key는 DB가 아니라 `.env`에만 둔다.

### search_feedback
`id PK`, `user_id`, `query TEXT`, `mode VARCHAR(20)` (GRID/FTS), `result_count`, `clicked_handover_id`, `rating SMALLINT`, `comment`, `created_at`

---

## 8. 무결성 / 정합성 규칙

1. `handovers.current_version_no` 는 반드시 `MAX(handover_versions.version_no)` 와 일치 (정합성 점검 API `/admin/integrity-check` 제공).
2. `handover_versions` 는 INSERT만 허용. 운영 DB에서는 앱 계정에 UPDATE/DELETE 권한을 부여하지 않는 것을 권장.
3. Soft Delete된 Handover는 모든 일반 질의에서 제외(리포지토리 기본 필터). ADMIN만 `include_deleted=true` 사용 가능.
4. `handover_statuses.category='CLOSED'` 인 상태만 완료로 간주(Carry Forward·My Work·지연 판정의 단일 기준).
5. 사용자 삭제는 비활성화(`is_active=false`)로만 수행. audit_logs·versions의 이름 컬럼은 비정규화되어 있어 증적이 남는다.
6. 첨부 파일 실제 삭제는 Soft Delete 후 보존기간 경과 시 배치로만. 삭제도 Audit.
