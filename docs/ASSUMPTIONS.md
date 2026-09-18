# ASSUMPTIONS.md — 가정 및 기본값 결정

> 요구사항에 명시되지 않아 **합리적 Default로 결정**한 사항 기록(§91).
> 각 항목은 사용자가 원하면 언제든 변경 가능하며, 변경 시 영향 범위를 함께 적었다.

---

## A. 환경 / 인프라

### A-01. PostgreSQL 미설치 환경 (실측 확인됨)
현재 PC에 PostgreSQL이 설치되어 있지 않고(`C:\Program Files\PostgreSQL` 없음, `psql` 없음, 서비스 없음),
시스템 Python/Node도 없다(codex 번들 런타임만 존재: Python 3.12.14 / Node 24.19.0).

**결정**
1. **운영 기본 DB는 PostgreSQL 16을 유지**한다(요구사항 §3). 스키마·인덱스·FTS 설계는 PG 기준.
2. `install.ps1`이 PostgreSQL을 탐지한다. 없으면
   - (a) 설치 안내(오프라인 설치 파일 경로 지정 가능), 또는
   - (b) **개발/평가 모드**로 SQLite를 사용해 즉시 구동(`DEV_DB=sqlite`).
3. SQLite 모드에서도 전 기능이 동작하도록 `search/backends/`를 방언별로 분리한다(FTS5 + LIKE).
   단, **운영 모드에서는 화면 상단에 상시 경고 배너**를 띄우고 `status.ps1`이 경고를 출력한다.
4. Alembic 마이그레이션은 방언 분기(`op.get_bind().dialect.name`)로 PG 전용 객체(tsvector/trgm/pgvector, 부분 인덱스 일부)를 조건부 생성한다.

**영향**: 개발·시연은 즉시 가능, 운영 이관 시 `pg_dump` 대신 마이그레이션 + 데이터 이관 스크립트 1회 실행 필요.

### A-02. 런타임 경로
시스템에 python/node가 없으므로 스크립트는 다음 순서로 탐색한다.
`PATH` → `%LOCALAPPDATA%\Programs\Python\Python312` → codex 번들(`%USERPROFILE%\.cache\codex-runtimes\...`).
`.env`의 `PYTHON_EXE`, `NODE_EXE`로 명시 지정 가능.

### A-03. 포트
백엔드/통합 서비스 `8080`, 개발용 Vite `5173`. `.env`의 `APP_PORT`로 변경.

### A-04. OneDrive 경로
프로젝트가 OneDrive 동기화 폴더 안에 있다. `node_modules`, `.venv`, `data/`, `backup/`, `logs/`, `run/` 은
동기화 대상에서 제외(문서 안내 + `.gitignore`)한다. 대용량 첨부/DB의 클라우드 동기화 충돌을 피하기 위해
`data/`의 기본 경로를 `.env`의 `DATA_DIR`로 분리 가능하게 한다.

### A-05. 시간대
전 시스템 **Asia/Seoul 고정**. DB는 TIMESTAMPTZ(UTC 저장), 표시·경계 계산(오늘/이번주/교대)은 KST.
"이번 주"는 **월요일 시작**. 회계연도 개념 미적용.

---

## B. 업무 규칙

### B-01. 교대 정의 (§27)
요구사항에 교대 시간이 없어 3교대 기본값을 둔다. 관리자 화면에서 변경 가능.
```
DAY   08:00 ~ 16:00
SWING 16:00 ~ 24:00
NIGHT 00:00 ~ 08:00 (crosses_midnight)
```
"현재 근무 중 신규"는 현재 교대 시작시각 이후 등록된 건으로 판정한다.

### B-02. 재확인(Re-Ack) 트리거 필드 (§33)
기본값 = `title, content, work_date, status_code, priority_code, assignee_id`.
`system_settings['ack.reack_fields']` 로 관리자 변경 가능. 비고/태그/첨부 변경은 재확인을 유발하지 않는다.

### B-03. 확인(Ack) 시 기록 버전
**전달 시점 버전이 아니라 "확인 버튼을 누른 시점의 current_version_no"** 를 기록한다.
전달 당시 버전은 `shift_handover_items.version_no_at_transfer`에 별도 보존한다.
→ "확인 이후 변경" 판정은 `current_version_no > acked_version_no AND 재확인 대상 필드 변경`.

### B-04. 미완료(Open) 판정
`handover_statuses.category` 로 단일 판정한다.
`OPEN` = 신규/진행중/확인필요/조치예정 · `WAITING` = 대기/보류 · `CLOSED` = 완료/취소.
Carry Forward·지연·My Work·Cockpit 모두 이 분류를 사용한다(중복 정의 금지).

### B-05. 지연(Overdue) 정의
`work_date < 오늘` 이고 상태 category ≠ CLOSED. Task는 `due_date < 오늘` 기준.

### B-06. Carry Forward 자동 범위
직전 교대 세션의 항목 중 CLOSED가 아닌 것을 **다음 Basket의 후보로 자동 담되, 해제 가능**하게 한다.
완전 자동 전달(사용자 확인 없이 SENT)은 하지 않는다 — 인계는 사람의 명시적 행위여야 증적 가치가 있다.

### B-07. 즐겨찾기 vs 상단고정
`★`(handover_stars)는 개인용, `상단고정`(is_pinned)은 전역용(MANAGER+). 목록 기본 정렬은
`is_pinned DESC → is_important DESC → registered_date DESC`.

### B-08. 삭제 권한
ANALYST는 삭제 불가(오등록 시 상태를 `취소`로 변경). Soft Delete는 MANAGER+, 물리 삭제는 제공하지 않는다.

### B-09. Handover 필수 입력
`company_id, title, content, registered_date, status_code, priority_code`. 그 외는 선택.
Excel Import 시에는 `title`이 없으면 `content`의 첫 60자를 제목으로 생성하고 `title_auto_generated=true`를
`raw`에 기록한다(원본 Excel에 제목 컬럼이 없기 때문 — §45).

### B-10. 관계사/인명 마스터 매칭
Import 시 자동 생성 OFF가 기본. 매칭 실패해도 `*_name_raw` 텍스트로 100% 보존하므로 데이터 손실 없음.
후속으로 관리자 화면에서 "미매핑 인명 일괄 연결" 도구를 제공한다(Phase 8).

---

## C. 검색 / 성능

### C-01. 한글 전문검색
형태소 분석기(mecab-ko 등) 설치를 강제하지 않는다. `pg_trgm` + `simple` tsvector 조합으로 구현하고,
검색 백엔드를 한 파일로 격리해 추후 교체 가능하게 한다(ARCHITECTURE §5.3).

### C-02. 기본 페이지 크기
50행. 선택 가능값 25/50/100/200. 200 초과 금지(브라우저 전체 로딩 방지 §51).

### C-03. 전체 건수 표시
필터가 없을 때의 "전체 N건"은 통계치(`reltuples`) 근사 허용(1분 캐시). "현재 검색결과 M건"은 정확한 count.

### C-04. Export 상한
기본 100,000행. 초과 시 "필터를 좁히거나 분할 내보내기" 안내. `.env`/설정으로 변경 가능.

---

## D. 이관 (Excel)

### D-01. 원본 파일
현재 `C:\Users\dewdrop\OneDrive\인수인계` 폴더는 비어 있어 실제 Excel을 확인하지 못했다.
따라서 §45의 8개 컬럼을 기준으로 **관대한 매핑기**를 구현하고, 헤더 이름 변형(공백·괄호·유사어)을
사전으로 흡수한다. 실제 파일 확보 시 매핑 사전을 보강한다(코드 수정 없이 설정으로 추가 가능하게 설계).

### D-02. 중복 Fingerprint
`sha256( norm(관계사) | 날짜(YYYY-MM-DD) | norm(내용 앞 500자) | norm(전달자) )`.
`norm` = 공백 정규화 + 소문자화 + 특수문자 제거. 중복 판정은 **의심 표시만**, 삭제·자동 병합 없음(§48).

### D-03. 날짜 파싱
Excel serial, `YYYY-MM-DD`, `YYYY.MM.DD`, `MM/DD`, `9월 16일`, `26-09-16` 등을 허용.
연도 없는 값은 Sheet 이름의 연도를 보완값으로 사용하고 `date_inferred=true`를 raw에 기록한다.

### D-04. Import 시 작성자
`created_by` = Import 실행 관리자, `sender_name_raw` = 원본 전달자 문자열.
v1 버전의 `changed_by`도 실행 관리자이며 `change_reason`에 job 코드를 남긴다(증적 명확화).

### D-05. 진행상황이 비었거나 모를 때의 상태 (Phase 4)
기본 `DONE`(완료). 마법사에서 바꿀 수 있다.
과거 Excel 기록은 대부분 끝난 일이다. 미완료로 넣으면 수천 건의 오래된 항목이 '미완료'·'지연'
목록을 채워 **진짜 남은 일이 묻힌다** — 그 자체가 누락이다. 모르는 값은 경고로 표시해 사람이 본다.

### D-06. '한 필드에 컬럼 하나' 는 Sheet 단위 (Phase 4)
연도별 Sheet 마다 헤더 표기가 다를 수 있다(2024 `진행상황`, 2025 `진행 상황`).
파일 전체 기준으로 제약하면 두 번째 Sheet 의 상태 컬럼이 매핑에서 빠진다. Sheet 안에서만 겹치지 않으면 된다.

### D-07. 등록되지 않은 관계사 (Phase 4)
값 매핑에서 (a) 기존 관계사 연결 (b) 새로 등록 (c) 그대로 중 고른다. 기본은 (c).
(c) 는 '미지정' 관계사로 들어가고 **원래 이름을 비고 맨 앞에 `[원본 관계사: X]` 로 남긴다**
(관계사 원문 컬럼이 없으므로). 비고는 통합 검색 대상이라 원래 이름으로도 찾을 수 있다.

### D-08. 중복 의심 · 오류 행의 기본 처리 (Phase 4)
- 오류 행: 가져올 수 없다. 사용자가 '가져오기'를 골라도 들어가지 않는다.
- 중복 의심: 기본 제외. 사람이 '가져오기'를 고른 경우에만 들어간다.
  같은 파일을 두 번 올려 전부 두 벌이 되는 사고를 막는다.
- 둘 다 **지우지 않는다**. staging 에 남아 있고 목록·실패행 Excel 로 확인할 수 있다.
- UI 로 등록한 건도 같은 식으로 지문을 계산한다. Excel 에 이미 입력해 둔 건을 알아볼 수 있어야 한다.

### D-09. Import 되돌리기 (Phase 4)
job 단위 Soft Delete. 단 **가져온 뒤 누군가 수정한 건(current_version_no > 1)은 지우지 않는다.**
되돌리기로 남의 작업을 날리면 그게 누락이다. 몇 건을 남겼는지 결과에 표시한다.

### D-10. Export 상한 (Phase 4)
`export.max_rows`(기본 100,000)를 넘으면 **잘라서 주지 않고 거부**한다. 잘린 파일을 받은 사람은
그게 전부인 줄 안다. 조건을 좁혀 나눠 받게 한다. 셀은 전부 문자열로 써서 수식 주입을 막는다.

### D-11. 백그라운드 작업과 재기동 (Phase 4)
Import 의 긴 단계는 요청 응답 뒤 같은 프로세스에서 돈다(F-03 단일 프로세스 전제).
재기동하면 RUNNING 으로 남은 작업을 FAILED 로 정리하고 멈춘 단계(phase)를 남긴다.
COMMIT 은 행 단위 멱등이라 다시 실행하면 남은 행만 들어간다.
**다중 워커로 늘릴 때는** 이 정리 로직이 다른 워커의 작업을 실패로 만들 수 있으므로 작업 소유자 표시가 필요하다.

---

## E. AI

### E-01. 기본값
`LLM_PROVIDER=disabled`, 4개 AI 토글 모두 OFF. 메뉴·라우트·API 전부 비노출(§54).

### E-02. 로컬 LLM
사내망 사용을 전제로 Ollama(`http://127.0.0.1:11434`)를 1순위 예시로 문서화한다. 이 PC에는 Ollama가
설치되어 있어 Phase 9 검증에 사용 가능. 임베딩 모델은 한국어 지원 모델(예: `bge-m3`) 권장.

### E-03. 근거 없는 답변
후보 0건이면 LLM을 호출하지 않고 즉시 "찾지 못했습니다"를 반환한다(토큰·지연 절약 + 환각 차단).

---

## F. 기술 선택

### F-01. Data Grid
**TanStack Table v8(headless) + 자체 셀 렌더링 + `@tanstack/react-virtual`** 을 사용한다.
요구된 기능(서버 페이징/필터/정렬/리사이즈/리오더/가시성/선택/키보드/대용량)을 모두 충족하면서
유료 라이선스 의존이 없다(AG Grid Enterprise 회피 §3).

### F-02. Calendar
FullCalendar(MIT 코어, 월/주/일 + DnD) 사용. 상용 플러그인 미사용.

### F-03. 백그라운드 처리
Celery/Redis를 도입하지 않는다(Windows 단일 노드에 과함). **APScheduler + DB 기반 Job 테이블**로
Import/Embedding/스윕을 처리하고, 프론트는 폴링한다.

### F-04. 실시간성
WebSocket을 도입하지 않는다. 알림·충돌 감지는 30초 폴링(`/notifications/unread-count`,
Drawer 열림 시 대상 handover의 `current_version_no`). 필요 시 Phase 10에서 SSE로 승격.

### F-05. 패키지 관리
백엔드는 `pip + requirements.txt`(버전 고정). 프론트는 **npm 우선, 없으면 pnpm** 순으로 자동 선택한다
(`Resolve-PackageManager`). 현재 이 PC에는 npm이 없고 번들 pnpm만 있어 pnpm 경로로 검증했다.
pnpm 사용 시 esbuild 네이티브 바이너리 설치 스크립트를 허용해야 하므로 `frontend/pnpm-workspace.yaml`에
`allowBuilds: { esbuild: true }`를 둔다(npm 사용 시 이 파일은 무시된다).
오프라인 설치는 사전 다운로드한 wheel/`node_modules` 사용 절차를 `INSTALL_WINDOWS.md` §6에 문서화했다.

### F-06. 프로세스 종료 시 자식 프로세스 정리 (Phase 1 실측)
일부 Python 배포판(이 PC의 번들 런타임 포함)에서는 venv의 `python.exe`가 실제 서버를 **자식 프로세스로**
띄운다. 부모 PID만 종료하면 포트가 계속 물려 있어 재기동이 실패하므로, `stop.ps1`은
(1) PID 파일의 프로세스와 그 자식들을 함께 종료하고 (2) 종료 후에도 포트가 LISTEN 이면 점유 프로세스를
추가로 정리한 뒤 (3) 그래도 남아 있으면 경고를 출력한다.

### F-07. 운영 스크립트의 접속 주소
`.env`의 `APP_HOST=0.0.0.0`은 **바인딩 주소**이지 접속 주소가 아니다. `backup.ps1`/`status.ps1` 등이
자기 자신을 호출할 때는 `127.0.0.1`로 정규화한다(`Get-ApiBaseUrl`). 감사 기록용
`POST /api/v1/audit/system-event`는 loopback 에서만, 허용된 Action(BACKUP/RESTORE)만 받는다.

---

## G. 미결 / 확인 요청 사항 (진행을 막지 않음, 기본값으로 진행 중)

| # | 항목 | 현재 기본값 | 확인되면 좋은 것 |
|---|---|---|---|
| G-01 | 교대 시간/조 편성 | 3교대 08/16/24 | 실제 교대 시간, 조 인원, 인계 대상(개인 vs 조) |
| G-02 | 관계사 목록 | Import에서 자동 수집 | 정식 관계사 코드/명 목록 |
| G-03 | 실제 Excel 파일 | 미확보(폴더 비어 있음) | 실파일 1개만 있어도 매핑 정확도 급상승 |
| G-04 | 상태값 실제 사용 문구 | §19 8종 | Excel '진행 상황' 컬럼의 실제 값 분포 |
| G-05 | 첨부 보관 정책 | 무기한 | 용량 한도·보존기간 |
| G-06 | Audit 보존기간 | 365일 | 사내 규정 |
| G-07 | 계정 체계 | Local | AD 연동 시점·도메인 |
