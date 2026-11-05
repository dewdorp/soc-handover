# SECURITY.md — 보안 설계

> 전제: 사내 내부망, 인터넷 차단 가능, Windows 단일 노드, 사용자 20~50명.
> 외부 공격보다 **증적 신뢰성 · 권한 오남용 방지 · 입력 신뢰 경계**가 우선순위.

---

## 1. 인증 (Authentication)

### 1.1 비밀번호
- 해시: **Argon2id** (`argon2-cffi`, time_cost=3, memory_cost=64MB, parallelism=2). bcrypt는 fallback.
- 정책(설정화): 최소 12자, 영문+숫자+특수 중 3종, 최근 3개 재사용 금지, 사용자명 포함 금지.
- **기본 관리자 비밀번호를 소스/스크립트에 하드코딩하지 않는다.** `install.ps1`이 대화식으로 입력받아 `.env`가 아닌 DB에 해시로만 저장하고, `must_change_password=true` 로 최초 로그인 시 변경을 강제한다.

### 1.2 토큰 / 세션
| 항목 | 값 |
|---|---|
| Access Token | JWT(HS256), 15분, **HttpOnly + SameSite=Lax + Secure(HTTPS 시)** 쿠키 |
| Refresh Token | 랜덤 256bit, 12시간(교대 근무 1회 길이), DB에 SHA-256 해시 저장, **1회용 회전** |
| 재사용 탐지 | 이미 회전된 refresh 재사용 시 해당 사용자의 전체 토큰 폐기 + Audit |
| CSRF | 더블 서브밋 쿠키(`csrf_token` 비-HttpOnly) + `X-CSRF-Token` 헤더 검증. GET/HEAD 제외 |
| 로그아웃 | refresh 폐기 + 쿠키 삭제, Audit(LOGOUT) |

JWT 시크릿은 `.env`의 `SECRET_KEY`(설치 시 자동 생성, 64byte 랜덤). 소스 기본값 없음 — 미설정 시 기동 실패시킨다.

### 1.3 Brute Force 방어
- 계정 단위: 5회 실패 → 5분 잠금, 10회 → 30분(`users.locked_until`).
- IP 단위: 20회/5분 초과 시 429.
- 실패 응답은 원인을 구분하지 않는다("아이디 또는 비밀번호가 올바르지 않습니다").
- 모든 시도는 `login_attempts` + Audit(LOGIN_FAILURE)에 기록.

### 1.4 확장 (AD/LDAP, §68)
```python
class AuthProvider(Protocol):
    async def authenticate(self, username: str, password: str) -> AuthResult: ...
    async def lookup(self, username: str) -> ExternalUser | None: ...
```
`LocalAuthProvider` 기본. `LDAPAuthProvider` 추가 시 사용자 프로비저닝(최초 로그인 시 생성)과 역할 매핑 테이블만 추가하면 되도록 인증과 인가를 분리한다. 비밀번호 검증 로직이 서비스 레이어에 새어나가지 않는다.

---

## 2. 인가 (Authorization / RBAC)

- 권한 문자열: `<resource>:<action>` (예: `handover:update`, `audit:read_all`, `import:rollback`).
- 라우터: `Depends(require("handover:update"))` — 없으면 403.
- 서비스: 소유권/담당자 검사(ANALYST는 본인 작성 또는 담당 건만 수정).
- **행 단위 필터링은 Repository에서 강제**(`base_query()`가 항상 soft-delete 및 권한 스코프 적용).
- 권한 매트릭스는 `docs/API.md §10` 단일 출처. 코드(`auth/rbac.py`)와 테스트(`test_rbac.py`)가 이 표를 그대로 검증한다.
- 역할 변경은 ADMIN만, 본인 역할 강등/자기 계정 비활성화 금지(잠금 방지).

---

## 3. 입력 신뢰 경계

| 위협 | 대응 |
|---|---|
| SQL Injection | SQLAlchemy 파라미터 바인딩 전용. **필터 DSL의 field/op는 화이트리스트 레지스트리에서만 해석** — 사용자 문자열이 식별자·연산자로 사용되는 경로 자체가 없음. 정렬 컬럼도 동일 |
| XSS | React 기본 이스케이프. `dangerouslySetInnerHTML` 전면 금지(ESLint 규칙). Diff 하이라이트는 텍스트 노드 + CSS로만 구현. Markdown 렌더링은 도입하지 않거나 sanitize 후 사용 |
| CSRF | §1.2 더블 서브밋 + SameSite. 상태 변경은 전부 비-GET |
| 대용량 요청 | 본문 1MB 제한, `size` 최대 200, 필터 조건 최대 20개, `in` 값 최대 500개 |
| 정규식/와일드카드 남용 | `contains`는 LIKE 이스케이프(`%`, `_`, `\`) 후 바인딩. 사용자 정규식 미지원 |
| 대량 조회 남용 | Export 최대 행수 설정(기본 100,000), Audit 조회 기간 필수 |
| Mass assignment | Pydantic 스키마에 정의된 필드만 반영. `current_version_no`, `created_by`, `is_deleted` 등은 서버 전용 |

---

## 4. 파일 업로드 (§64)

| 통제 | 내용 |
|---|---|
| 확장자 | allowlist 방식 (기본: png jpg jpeg gif pdf txt log csv xlsx xls docx pptx zip 7z). 설정 변경 가능 |
| 실제 타입 | 매직바이트 검사(확장자-내용 불일치 거부). `.html/.svg/.js/.exe/.bat/.ps1` 등은 allowlist에 넣지 않음 |
| 크기 | 기본 20MB/파일, 100MB/요청 (설정) |
| 저장 | `data/attachments/<yyyy>/<mm>/<uuid>.<ext>` — **원본 파일명으로 저장하지 않는다** |
| Path Traversal | 저장 경로는 UUID로 서버가 생성. 사용자 입력 경로 미사용. 다운로드는 DB의 id로만 조회 후 절대경로 정규화 검증 |
| 다운로드 | `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff` + 고정 `application/octet-stream` (브라우저 렌더 방지) |
| 무결성 | SHA-256 저장, 중복 업로드 감지 |
| 백신 | `scan_status` 필드 + `AttachmentScanner` 인터페이스(기본 NoopScanner). 사내 백신 CLI 연동 확장점 |
| 감사 | 업로드/다운로드/삭제 전부 Audit |

---

## 5. 감사 증적 (Audit)

- **Version History(내용 변경)와 Audit Log(행위)는 분리**한다(§59).
- Audit 기록 실패가 업무 트랜잭션을 실패시키지 않도록 하되, **기록 누락은 경고 로그 + 카운터**로 감시한다.
  단, `LOGIN_*`, `ROLE_CHANGE`, `SETTING_CHANGE`, `HANDOVER_DELETE`, `IMPORT_ROLLBACK`, `RESTORE` 는 **동일 트랜잭션에 기록하고 실패 시 작업도 롤백**한다(고위험 행위 증적 보장).
- `audit_logs`는 애플리케이션에서 UPDATE/DELETE 하지 않는다. 보존기간 경과분만 ADMIN 배치로 아카이브(내보내기 후 삭제, 그 행위도 Audit).
- 비밀번호/토큰/API Key는 `before_value/after_value`에 절대 기록하지 않는다(`***`로 마스킹, 마스킹 대상 필드 목록을 코드에 상수로 관리).
- `client_ip`는 `X-Forwarded-For` 를 신뢰하지 않는다(프록시 미사용 전제). 프록시 도입 시 신뢰 프록시 목록 설정을 추가한다.

---

## 6. 전송 / 배포 보안

- 기본은 HTTP(내부망). **HTTPS 옵션 제공**: `.env`의 `SSL_CERTFILE/SSL_KEYFILE` 설정 시 uvicorn TLS 기동, 쿠키 `Secure` 자동 활성.
- 보안 헤더: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Content-Security-Policy: default-src 'self'` (외부 CDN 미사용 — 오프라인 요구와도 일치), `Permissions-Policy` 최소화.
- CORS: 기본 비활성(동일 출처 서빙). 개발 모드에서만 `localhost:5173` 허용.
- `/api/docs`는 기본 비활성(`ENABLE_DOCS=false`), 활성 시 ADMIN 인증 필요.
- 서버 오류는 사용자에게 `request_id`만 노출. 스택트레이스·SQL은 로그 파일로만.

---

## 7. 비밀 관리

```
.env            (git 제외, 설치 시 생성)
  SECRET_KEY=<64byte random>
  VAULT_KEY=<32byte random, base64>      # 장비 비밀번호 보관용(§7.1)
  DATABASE_URL=postgresql+psycopg://soc_app:<pw>@127.0.0.1:5432/soc_handover
```
- 소스·문서·스크립트에 실제 비밀번호/키를 넣지 않는다. `.env.example`에는 자리표시자만.
- DB 계정 분리 권장: 마이그레이션용(DDL)과 애플리케이션용(DML, `handover_versions`·`audit_logs`에 UPDATE/DELETE 없음).
- 설정 API는 `is_secret=true` 값을 마스킹해서 반환하고, 변경 시 이전 값을 Audit에 남기지 않는다(변경 사실만 기록).

### 7.1 장비 비밀번호 보관 (credentials)

| 항목 | 방식 |
|---|---|
| 암호 | AES-256-GCM, 항목마다 무작위 nonce(12B), 인증 태그로 변조 탐지 |
| 묶음(AAD) | `credential:{id}` — 다른 항목의 암호문을 옮겨 붙여도 열리지 않는다 |
| 키 | `.env` 의 `VAULT_KEY`(base64 32B). DB 에는 키가 없다 — 덤프만으로는 못 읽는다 |
| 키 교체 | 암호문 첫 바이트에 키 버전. `VAULT_KEY_NEXT` + `manage.py vault-rekey` 로 전부 재암호화 |
| 열람 | 본인 계정 비밀번호 재확인 → 한 건씩 `CREDENTIAL_REVEAL` 감사(실패는 `CREDENTIAL_REVEAL_DENIED`) |
| 범위 | SHARED(교대 근무자 전원) · PERSONAL(등록자만). 남의 PERSONAL 은 404 로 존재 자체를 감춘다 |
| 이력 | 바꾸기 전 값을 암호문으로 최근 5개까지. 옛 값 열람도 같은 감사 기록 |
| 나가는 곳 | `/reveal` 두 경로뿐. 목록 · 상세 · 이력 · 검색 · Export 어디에도 값이 없다 |

- 운영(`APP_ENV=prod`)에서 `VAULT_KEY` 가 없으면 **그 기능만** 꺼진다(다른 기능은 그대로 동작).
  개발·테스트에서는 `SECRET_KEY` 에서 만들어 쓴다 — 운영에서 그렇게 하면 SECRET_KEY 교체가
  보관된 비밀번호를 전부 잠근다.
- **`.env` 를 잃으면 보관된 비밀번호는 복구할 수 없다.** DB 백업과 별도로 `.env` 를 안전한 곳에 둔다.

---

## 8. Rate Limiting

| 대상 | 한도 |
|---|---|
| `/auth/login` | IP당 20회/5분, 계정당 5회/5분 |
| 검색/목록 API | 사용자당 120회/분 |
| Export / Import commit | 사용자당 5회/분, 동시 1건 |

인메모리 토큰 버킷(단일 프로세스 전제). 다중 워커 도입 시 DB/파일 기반으로 승격.

---

## 9. 백업 / 복구 보안

- `backup.ps1`: `pg_dump -Fc` + `data/attachments` 압축. 파일명에 타임스탬프. 보존 N일(기본 30).
- 백업 파일은 별도 경로/네트워크 드라이브 복사를 권장(스크립트 인자로 지원).
- `restore.ps1`: 대상 파일 표시 → **"현재 데이터가 삭제됩니다" 확인 문구 입력** 요구 → 복구.
- BACKUP/RESTORE 모두 Audit 기록(스크립트 → API 호출, 실패해도 작업은 진행하고 로그 남김).
- 백업 파일에는 전체 인수인계 내용이 포함되므로 접근 권한(NTFS ACL)을 관리자만으로 제한하도록 문서에 명시.

---

## 10. 개인정보 / 데이터 최소화

- 수집 항목은 업무 식별에 필요한 최소(성명, 사번/계정, 소속, 연락처(선택)).
- 인수인계 본문에 개인정보·계정정보를 넣지 않도록 작성 가이드를 등록 화면 힌트로 제공.
- 사용자 삭제는 비활성화로만 처리(증적 보존). 실제 파기 필요 시 ADMIN이 익명화 절차(표시명 → `퇴사자#<id>`) 수행, 이 또한 Audit.

---

## 10-1. 열람 그룹 — 데이터 단위 접근 통제 (1.3.0)

역할(RBAC)은 **행위**를 가르고, 그룹은 **데이터**를 가른다. 둘을 한 곳에 섞으면 "관리자니까
보인다"가 생긴다. 그래서 열람 판정에 역할을 쓰지 않는다.

### 설계 원칙

1. **판정은 한 곳에서만 만든다** — `group_service.visible_clause()`. 질의를 만드는 자리가
   전부 그것을 지나므로(`handover_repo._scope`, `handover_service.get_or_404`), 새 화면을
   붙이면서 조건을 빼먹을 수 없다. 통제를 여러 곳에 흩어 놓으면 반드시 한 곳이 빠진다.
2. **거절은 404 로** — 403 은 '그 번호의 업무가 있다'를 알려 준다. 못 보는 것은 없는 것이다.
3. **역할 우회 없음** — ADMIN · MANAGER 도 자기 그룹만 본다. `group:manage` 는 그룹을
   만들고 사람을 넣는 권한이지 원문을 읽는 권한이 아니다.
4. **회수는 다음 요청부터** — 멤버십을 DB 에서 그때그때 읽는다(캐시 없음). 그룹을 비활성으로
   바꾸면 구성원을 지우지 않아도 그 즉시 끊긴다.
5. **이미 발급된 산출물도 막는다** — Export 내려받기 토큰에 발급 당시의 소속을 적어 두고,
   받을 때 지금 소속과 비교해 좁아졌으면 거절한다. 그렇지 않으면 권한 회수 뒤에도 링크
   하나로 내용이 빠져나간다.
6. **숫자도 통제한다** — '전체 N건'과 통계 집계도 같은 범위에서 센다. 제목을 못 봐도
   '저쪽에 몇 건 있다'와 '어느 관계사를 상대한다'가 숫자로 새어 나간다.

### 통제가 걸리는 자리

목록 · 건수 · 패싯 · 상세 · 변경이력 · as-of · 타임라인 · 확인(ack) · 확인 대기 목록 ·
첨부 목록/미리보기/받기/삭제 · 댓글 읽기·쓰기·고치기·지우기 · 연결된 할 일/일정 생성 ·
달력의 인수인계 레이어 · 내 업무 · 검색/저장된 보기 · 알림 목록과 안 읽음 수 ·
통계 · Excel 내보내기 · 내려받기 토큰 · 교대 바구니 담기 · RAG 사례.

### 전파는 범위를 넓히는가

아니다. 전파(`POST /handovers/{id}/propagate`)는 **사람을 거는 것**이지 글을 여는 것이
아니다. `visibility` 와 공개 그룹은 그대로이고, 걸린 사람만 당사자로서 그 건을 본다.
누가 · 언제 · 어느 그룹에 · 몇 명에게 퍼뜨렸는지가 감사에 남는다(`HANDOVER_PROPAGATE`).

그룹을 통째로 여는 것과 다른 점: 그룹 공개는 **앞으로 그 그룹에 들어올 사람까지** 보게
되지만, 전파는 **그때 그 사람들**만 걸린다. 나중에 CERT 에 들어온 사람은 그 건을 보지 못한다.

전파로 사람을 **뺄 수는 없다**(더하기만). 빼는 것은 담당 · 전파 대상 바꾸기
(`PUT …/participants`)이고, 그쪽은 본문 수정과 같은 자격을 요구한다.

### 예외 (의도한 것)

내가 **당사자**인 건(작성 · 전달 · 담당 · 확인), 교대 인계로 **받은** 건, 그리고 공동 담당 ·
필수 인수자 · 참고로 **걸린** 건은 그룹과 무관하게 보인다. 이것이 없으면 그룹이 바뀌는 순간 내 담당 업무가 내 화면에서 사라지고, 인계를 받고도
열 수 없는 상태가 생긴다.

### 감사

`GROUP_CREATE` · `GROUP_UPDATE` · `GROUP_MEMBER_CHANGE` · `GROUP_DATA_MOVE` ·
`HANDOVER_SCOPE_CHANGE` 는 **CRITICAL_ACTIONS** 다 — 감사 기록에 실패하면 업무 트랜잭션도
롤백된다. 누가 무엇을 볼 수 있는지 바꾼 기록이 남지 않으면 그 변경을 되돌릴 근거가 없다.

---

## 11. 보안 테스트 항목 (Phase 10)

1. 권한 매트릭스 전수 테스트 — 각 역할 × 각 엔드포인트(403 기대 경로 포함).
2. 타 사용자 자원 접근(IDOR): 남의 Basket/알림/개인 SavedView/첨부 직접 ID 접근 403.
3. 필터 DSL 인젝션: `field`에 `id; DROP` 류 입력 → 422.
4. 파일 업로드: 확장자 위조, 이중 확장자, 경로 조작(`..\`), 대용량, 0바이트.
5. CSRF: 헤더 없는 POST 차단 확인.
6. Brute force 잠금 동작 및 Audit 기록.
7. Version 불변성: API/서비스 경로로 과거 버전 수정·삭제 불가 확인.
8. Soft delete 우회 조회 불가(일반 사용자).
9. 비밀번호/토큰이 Audit·로그·응답에 노출되지 않음(로그 grep 검사).
10. AI 는 범위에서 제외 — `/api/v1/ai/*` 경로가 없다(404). 외부 LLM 으로 데이터가 나가는 경로도 없다.
