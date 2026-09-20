# INSTALL_WINDOWS.md — 설치 안내

설치 방법은 두 가지입니다.

| | A. 오프라인 설치 패키지 (운영 PC · **권장**) | B. 소스 설치 (개발 PC) |
|---|---|---|
| 대상 | 인터넷이 없는 사내 PC | 개발 · 시험용 PC |
| 필요한 것 | 없음 (Windows 10/11 64비트 + 관리자 권한) | Python 3.12, Node.js 20+, 인터넷 |
| DB | PostgreSQL 16 을 함께 설치 | SQLite(기본) 또는 따로 설치한 PostgreSQL |
| 실행 | 부팅 시 자동(서비스 모드) 또는 수동 | `start.ps1` |
| 파일 | `SOC-Handover-<버전>-offline.zip` | 이 저장소 |

---

## A. 오프라인 설치 패키지

### A-1. 패키지 만들기 (인터넷 되는 개발 PC 에서)

```powershell
.\package.ps1 -Download
```

- 처음 한 번은 `-Download` 로 외부 배포 파일을 `build\cache` 에 받습니다(이후에는 없어도 됨).
  - PostgreSQL 16 Windows binaries (EnterpriseDB 공식, 약 317MB)
  - Visual C++ 재배포 패키지 (Microsoft 공식, 약 25MB)
  - Python 라이브러리 wheel (PyPI, `backend\requirements.lock` 버전 그대로)
- 결과: `build\dist\SOC-Handover-<버전>-offline.zip` (약 110MB, 풀면 약 235MB) + `.sha256`
- Python 런타임은 이 PC 의 Python 3.12(개발 venv 의 원본)를 복사해 라이브러리까지 설치한 상태로 넣습니다.
- 버전은 `backend\app\__init__.py` 의 `__version__` 입니다. 새로 배포할 때 올리십시오.

zip 을 USB · 공유 폴더로 옮길 때 `.sha256` 도 함께 옮기면 받은 쪽에서 확인할 수 있습니다.

```powershell
Get-FileHash .\SOC-Handover-1.0.0-offline.zip -Algorithm SHA256
```

### A-2. 설치 (대상 PC)

zip 을 풀고 **`INSTALL.cmd` 더블클릭** → 권한 요청 [예] → `Y` → 관리자 비밀번호 두 번. 끝입니다.
자세한 안내는 패키지 안의 `README-KO.txt`, 설치 뒤 운영은 설치 폴더의 `docs\OPERATIONS.md` 를 보십시오.

| 옵션 | 뜻 |
|---|---|
| `INSTALL.cmd -InstallDir D:\SOC-Handover` | 설치 위치(영문 · 숫자 경로) |
| `INSTALL.cmd -AppPort 8090` | 화면 포트 |
| `INSTALL.cmd -Manual` | 수동 모드(자동 시작 · 서비스 · 방화벽 등록 없음, 관리자 권한 불필요) |
| `INSTALL.cmd -NoFirewall` | 방화벽 규칙을 만들지 않음 |

설치 프로그램이 확인 · 처리하는 것:

- Windows 10 이상 64비트, 디스크 3GB, 포트 비어 있음, 경로(영문 · 공백 없음 · OneDrive 밖)
- 패키지 파일 7,600여 개의 SHA-256 — USB 복사 손상을 설치 전에 잡습니다
- 인터넷에서 받은 zip 의 '차단' 표시(Mark of the Web) 해제
- Visual C++ 런타임(없거나 오래됐을 때만 설치)
- PostgreSQL 초기화: UTF8 · 로케일 C(Windows 지역 설정과 무관), 127.0.0.1 에서만 접속, 비밀번호 자동 생성
- 폴더 권한: 데이터 · 백업 · 로그 · `.env` 는 관리자와 설치한 사용자만
- 서비스 모드: DB 서비스(`SOC-Handover-DB`), 앱 자동 시작 · 재시작(작업 스케줄러 `SOC-Handover`),
  매일 03:00 백업(`SOC-Handover-Backup`), 방화벽(앱 포트)

**다시 실행해도 안전합니다.** 중간에 멈췄으면 같은 설정으로 이어서 진행하고, 설치가 끝난 폴더에 다시 실행하면
업그레이드(먼저 DB 백업 → 파일 교체 → DB 구조 갱신 → 재시작)합니다.

### A-3. 호환성 메모

| 항목 | 기준 |
|---|---|
| OS | Windows 10 (1809 이상 권장) / 11, 64비트. Windows 7 · 8 · 32비트는 Python 3.12 가 지원하지 않음 |
| PowerShell | Windows 기본 5.1 (설치 스크립트는 5.1 기준으로 작성, UTF-8 BOM) |
| 한국어 Windows | 모든 경로 · 파일 이름은 영문. 스크립트 출력은 한글, DB 메시지는 영어(lc_messages=C) |
| 다른 Python / PostgreSQL 이 이미 있는 PC | 영향 없음 — 설치 폴더 안의 것만 씀. DB 포트는 5432 부터 비어 있는 것을 고름 |
| **Smart App Control** (Windows 11) | **켜져 있으면 설치 실패.** PostgreSQL 배포 파일(EnterpriseDB)에는 코드 서명이 없어 실행이 막힙니다(개발 PC 에서 실측 — `pg_ctl.exe` 차단). 설치 프로그램이 미리 확인하고 해결 방법을 안내합니다. 관리 대상 사내 PC · 업그레이드로 설치한 Windows 11 은 보통 꺼져 있습니다 |
| 프록시 · 인터넷 차단 | 설치 · 실행 모두 인터넷을 쓰지 않음. 화면도 외부 글꼴 · CDN 을 쓰지 않음 |
| 브라우저 | Chrome · Edge (최근 3년 안의 버전). Internet Explorer 불가 |

**Windows 10 호환성 근거** (실제 Windows 10 PC 에서의 실행 확인은 현장 설치 때 함께 합니다)

| 확인한 것 | 결과 |
|---|---|
| 패키지에 든 실행 파일의 최소 OS(PE 헤더) | Python · PostgreSQL · libpq · 확장 모듈 모두 `6.0`(Vista 이상) — Windows 10 에서 막히는 것 없음 |
| 공급사 지원 범위 | Python 3.12 = Windows 8.1+, PostgreSQL 16 = Windows 10+, VC++ 2015-2022 재배포 = Windows 10+ |
| 설치 · 운영 스크립트가 쓰는 PowerShell 명령 | NetTCPIP · NetSecurity(방화벽) · ScheduledTasks · Unblock-File · Expand-Archive — 모두 Windows 8/10 의 PowerShell 5.1 기본 제공 |
| Windows 11 전용 기능 의존 | 없음. Smart App Control 확인은 레지스트리 키가 없으면 '꺼짐'으로 본다(Windows 10 에는 그 기능 자체가 없음) |
| 32비트 Windows | 지원하지 않음(64비트 전용) |
| PostgreSQL 절차 언어 모듈(plperl · plpython3 · pltcl) | 패키지에서 뺐다 — Perl · Tcl 런타임을 요구하는데 우리는 쓰지 않는다(plpgsql · pg_trgm 만 사용) |

> **Windows 10 Enterprise LTSC 2019 주의**: LTSC 에는 Microsoft Edge · Chrome 이 **들어 있지 않습니다**(Internet Explorer 11만 있음).
> 서버 PC 는 브라우저가 없어도 되지만, **접속해서 쓰는 PC 에는 Edge 또는 Chrome 을 설치**해야 합니다(IE 로는 화면이 열리지 않습니다).
> 최신 Edge · Chrome 모두 Windows 10 1809(LTSC 2019)를 지원합니다.

---

## B. 소스 설치 (개발 PC)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\install.ps1
.\start.ps1
```

- `install.ps1`: `.env` 생성 → `backend\.venv` + `requirements.txt` → 마이그레이션 → 기준 데이터 → 관리자 → 화면 빌드
- 테스트까지 하려면: `backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt`
- 기본 DB 는 SQLite(개발 · 평가용, 화면에 경고 표시). PostgreSQL 을 쓰려면 `.env` 의 `DATABASE_URL` 을 바꾸고 `install.ps1` 재실행.
- 백엔드 테스트:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

PostgreSQL 에서 같은 테스트를 돌리려면(운영 DB 와 같은 방언 — 테스트 전용 DB 를 주십시오, 스키마를 지우고 다시 만듭니다):

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://soc_test:<비밀번호>@127.0.0.1:5432/soc_test"
.\.venv\Scripts\python.exe -m pytest -q
```

### 개발 PC 문제 해결

| 증상 | 조치 |
|---|---|
| `이 시스템에서 스크립트를 실행할 수 없으므로` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force` |
| `Python 3.12 를 찾지 못했습니다` | Python 설치 시 "Add to PATH", 또는 `.env` 에 `PYTHON_EXE=` |
| 기동은 됐는데 화면이 안 나옴 | `frontend` 에서 `npm run build` (또는 `install.ps1` 재실행) |
| OneDrive 폴더에서 느림 · 충돌 | `node_modules` · `.venv` · `data` · `backup` · `logs` 를 동기화에서 제외 |

---

## C. 다른 PC 로 데이터 옮기기

- **PostgreSQL → PostgreSQL** (설치 패키지끼리): 옛 PC 에서 `backup.cmd` → `backup\*.dump`(+ `_attachments.zip`)를
  새 PC 의 `backup` 폴더로 복사 → 새 PC 에서 `restore.cmd`. 계정 · 비밀번호도 옛 PC 것이 됩니다.
- **SQLite(개발 PC) → PostgreSQL**: 직접 복구는 안 됩니다. 화면의 Excel 내보내기 → 새 PC 에서 Excel 가져오기로 옮깁니다.
- `.env` 는 옮기지 않습니다(새 PC 에서 새로 만든 비밀번호 · 비밀키를 씀).
