# SOC 교대근무 인수인계 · 업무관리 플랫폼

24×365 SOC 교대근무 환경에서 **업무 연속성**을 확보하기 위한 인수인계·할일·일정·검색·이력관리 통합 플랫폼입니다.
게시판이나 단순 TODO가 아닙니다. AI 기능은 없습니다(범위에서 제외).

```
빠르게 찾는다 · 놓치지 않는다 · 누가 담당하는지 안다 · 다음 교대자에게 정확히 전달한다
확인 여부가 남는다 · 모든 수정 이력이 남는다 · 과거 시점을 복원할 수 있다 · 감사 증적을 제공한다
```

---

## 빠른 시작 (Windows 10/11)

PowerShell을 열고 프로젝트 폴더에서 아래를 순서대로 실행합니다.
자세한 절차와 문제 해결은 [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md)를 보십시오.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\install.ps1
```

```powershell
.\start.ps1
```

브라우저(Chrome / Edge)에서 `http://localhost:8080/` 으로 접속하고, 설치 시 지정한 `admin` 계정으로 로그인합니다.

| 명령 | 설명 |
|---|---|
| `.\install.ps1` | 설치(전제조건 확인 → 의존성 → DB → 관리자 계정 → 프론트 빌드) |
| `.\start.ps1` | 기동 (`-Foreground` 콘솔 실행, `-Dev` 자동 리로드) |
| `.\stop.ps1` | 중지 |
| `.\status.ps1` | 프로세스·포트·DB·마이그레이션·백업 상태 점검 |
| `.\backup.ps1` | DB + 첨부파일 백업 (`-KeepDays`, `-Destination`) |
| `.\restore.ps1` | 백업에서 복구 (확인 문구 입력 필요) |
| `.\package.ps1` | **다른 PC로 옮길 배포 패키지 생성** (`-Offline`, `-IncludeData`) |

---

## 시스템 구성

```
Chrome / Edge ──▶ Uvicorn(FastAPI) :8080 ──▶ PostgreSQL 16
                    │  /        빌드된 React SPA
                    │  /api/v1  REST API
                    └─ data/attachments · data/imports · backup
```

- **Windows 네이티브 실행.** Docker 불필요, 리버스 프록시 불필요(단일 포트에서 UI+API 동시 서빙).
- **운영 DB는 PostgreSQL.** 미설치 환경에서는 개발/평가용 SQLite로 자동 전환되며, 화면과 `status.ps1`에 경고가 표시됩니다.
- **AI 없음.** 자연어 검색 · 요약 같은 AI 기능은 만들지 않기로 했습니다(docs/ASSUMPTIONS.md E-01). 외부로 데이터가 나가는 경로가 없습니다.

| 영역 | 기술 |
|---|---|
| Frontend | React 18 · TypeScript · Vite · Tailwind CSS · TanStack Query/Table/Virtual |
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 · Uvicorn |
| Database | PostgreSQL 16 (`pg_trgm` + `tsvector`) / SQLite(개발·테스트) |
| 인증 | Argon2id · HttpOnly 쿠키(Access 15분 + 회전형 Refresh) · CSRF 더블 서브밋 · RBAC |

---

## 폴더 구조

```
soc-handover/
├─ docs/                설계 문서 (아래 표 참조)
├─ backend/
│  ├─ app/
│  │  ├─ core/          설정·DB·보안·시간·미들웨어
│  │  ├─ models/        SQLAlchemy 모델(30 테이블)
│  │  ├─ schemas/       Pydantic 입출력
│  │  ├─ api/v1/        라우터
│  │  ├─ services/      도메인 로직(트랜잭션 경계)
│  │  ├─ repositories/  질의 전담
│  │  ├─ auth/          인증 Provider · RBAC
│  │  ├─ search/        필터 DSL · 검색 백엔드
│  │  ├─ importers/     Excel 이관
│  │  └─ audit/         감사 기록
│  ├─ alembic/          마이그레이션
│  ├─ tests/            실제 DB·실제 API 기반 테스트
│  └─ manage.py         bootstrap / create-admin / check
├─ frontend/src/
│  ├─ layouts/          AppShell · Sidebar · Topbar
│  ├─ features/         도메인별 화면
│  ├─ components/       공용 UI · DataGrid
│  ├─ services/api/     타입 안전 API 클라이언트
│  └─ hooks/ stores/ types/
├─ scripts/common.ps1   PowerShell 공통 유틸
└─ install/start/stop/status/backup/restore/package.ps1
```

---

## 설계 문서

| 문서 | 내용 |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 기능/비기능 요구사항, 수용기준, 우선순위 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 도메인·시스템 구조·Version/교대/검색/이관 설계·위험요소 |
| [docs/ERD.md](docs/ERD.md) | 30개 테이블 정의와 인덱스 전략 |
| [docs/API.md](docs/API.md) | REST API 구조와 RBAC 매트릭스 |
| [docs/UI_STRUCTURE.md](docs/UI_STRUCTURE.md) | 사이트맵·와이어프레임·단축키·표기 규칙 |
| [docs/SECURITY.md](docs/SECURITY.md) | 인증·인가·입력 신뢰 경계·업로드·감사·백업 보안 |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | 요구사항에 없어 기본값으로 정한 사항 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 설치 PC 운영 — 켜고 끄기 · 백업/복구 · 업그레이드 · 문제 해결 |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md) | 50만 건 성능 측정 결과와 고친 내용 |

---

## 구현 현황

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 설계 문서 7종 | ✅ 완료 |
| 1 | 인증·RBAC·감사 기반·DB 스키마·Windows 실행환경·AppShell | ✅ 완료 |
| 2 | 인수인계 CRUD · Version · Diff · 복원 · 낙관적 잠금 | ✅ 완료 |
| 3 | Data Grid · 컬럼 필터 · 검색 · 저장된 보기 · 통합검색(Ctrl+K) | ✅ 완료 |
| 4 | Excel Import 마법사 · 중복검사 · Export | ✅ 완료 |
| 5 | 교대 인수인계 · 확인(ack) · 재확인 · Carry Forward | ✅ 완료 |
| 6 | Task · Checklist · My Work · Board | ✅ 완료 |
| 7 | 일정(Calendar) 및 연계 | ✅ 완료 |
| 8 | 감사로그 · 관리자 · 설정 · 통계 · 댓글 · 첨부 · 알림 · 백업 현황 | ✅ 완료 |
| 9 | ~~AI 어댑터 · 하이브리드 RAG~~ | 범위에서 제외 |
| 10 | 성능 · 보안 · E2E · 오프라인 설치 패키지 · 문서 | ✅ 완료 |

---

## 개발

```powershell
# 백엔드 (자동 리로드)
.\start.ps1 -Dev

# 프론트엔드 개발 서버 (별도 터미널, http://127.0.0.1:5173)
cd frontend
npm run dev        # npm 이 없으면 pnpm run dev
```

```powershell
# 테스트
cd backend
.\.venv\Scripts\python.exe -m pytest
```

```powershell
# 마이그레이션 추가
cd backend
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "설명"
.\.venv\Scripts\python.exe -m alembic upgrade head
```
