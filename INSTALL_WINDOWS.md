# INSTALL_WINDOWS.md — Windows 10 설치 안내

이 문서의 명령은 **복사해서 그대로 붙여넣으면** 동작하도록 작성했습니다.
PowerShell을 사용하며, 관리자 권한은 PostgreSQL 설치 단계에서만 필요합니다.

---

## 0. 준비물

| 항목 | 필요 여부 | 비고 |
|---|---|---|
| Windows 10/11 | 필수 | |
| Python 3.12 | 필수 | 없으면 설치 단계에서 안내됩니다 |
| PostgreSQL 16 | **운영 필수 / 평가 시 선택** | 없으면 평가용 SQLite로 자동 진행 |
| Node.js 20+ | 화면(UI) 사용 시 필수 | 없으면 API만 동작 |
| 인터넷 | 최초 1회 | 패키지 다운로드용. 이후 오프라인 운영 가능 |

> 사내망이라 인터넷이 막혀 있으면 "6. 오프라인 설치"를 참고하십시오.

---

## 1. PowerShell 실행 정책

스크립트 실행이 차단되어 있으면 아래를 먼저 실행합니다. **현재 창에만** 적용되며 시스템 설정을 바꾸지 않습니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

---

## 2. Python 설치 확인

```powershell
python --version
```

`3.12.x`가 출력되면 넘어갑니다. 아무것도 나오지 않거나 Microsoft Store 창이 뜨면 설치가 필요합니다.

1. https://www.python.org/downloads/ 에서 Python 3.12 설치 파일을 받습니다.
2. 설치 화면 첫 페이지에서 **"Add python.exe to PATH"를 반드시 체크**합니다.
3. 설치 후 PowerShell을 새로 열고 `python --version`을 다시 확인합니다.

이미 다른 경로에 Python이 있다면, 설치 후 생성되는 `.env`에 아래 한 줄을 넣어 지정할 수 있습니다.

```
PYTHON_EXE=C:\Python312\python.exe
```

---

## 3. PostgreSQL 설치 (운영 환경)

평가·시연만 할 예정이면 **이 단계를 건너뛰어도 됩니다**(SQLite로 자동 진행).
실제 운영에는 PostgreSQL을 사용하십시오.

1. https://www.postgresql.org/download/windows/ 에서 PostgreSQL 16 설치.
2. 설치 중 입력한 `postgres` 비밀번호를 기억합니다.
3. 데이터베이스와 전용 계정을 만듭니다. (`<비밀번호>`를 실제 값으로 바꾸십시오)

```powershell
$env:PGPASSWORD = Read-Host "postgres 비밀번호" -AsSecureString | ConvertFrom-SecureString -AsPlainText
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER soc_app WITH PASSWORD '<비밀번호>';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE soc_handover OWNER soc_app ENCODING 'UTF8';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -d soc_handover -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

4. 설치 후 만들어지는 `.env`에서 접속 문자열을 수정합니다.

```
DATABASE_URL=postgresql+psycopg://soc_app:<비밀번호>@127.0.0.1:5432/soc_handover
```

---

## 4. 설치 실행

프로젝트 폴더에서:

```powershell
.\install.ps1
```

수행 내용은 다음과 같습니다.

```
전제조건 확인 → .env 생성(SECRET_KEY 자동 난수) → Python 가상환경 + 의존성
  → DB 마이그레이션 → 기준 데이터(상태·중요도·교대·설정) → 관리자 계정 → 프론트엔드 빌드
```

관리자 비밀번호는 설치 중 **직접 입력**합니다(화면에 표시되지 않고 해시만 저장됩니다).

- 12자 이상
- 영문 대문자·소문자·숫자·특수문자 중 3종 이상
- 계정명(`admin`) 포함 금지

> 최초 로그인 시 비밀번호를 한 번 더 변경해야 시스템을 사용할 수 있습니다.

`.env`의 `DATABASE_URL`을 나중에 PostgreSQL로 바꿨다면 `install.ps1`을 다시 실행하면 됩니다(여러 번 실행해도 안전).

---

## 5. 기동 및 접속

```powershell
.\start.ps1
```

```
  접속 주소 : http://<컴퓨터이름>:8080/
```

같은 PC에서는 `http://localhost:8080/`, 사내망의 다른 PC에서는 위 주소로 접속합니다.
Chrome 또는 Microsoft Edge를 사용하십시오.

상태 확인 / 중지:

```powershell
.\status.ps1
```

```powershell
.\stop.ps1
```

### 방화벽 (다른 PC에서 접속할 때만)

관리자 권한 PowerShell에서 1회 실행합니다.

```powershell
New-NetFirewallRule -DisplayName "SOC Handover 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Domain,Private
```

### 부팅 시 자동 실행 (선택)

작업 스케줄러에 등록합니다. 관리자 권한 PowerShell에서:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\start.ps1`""
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "SOC-Handover" -Action $action -Trigger $trigger -RunLevel Highest -User "SYSTEM"
```

---

## 6. 오프라인 설치 (인터넷 차단 환경)

인터넷이 되는 PC에서 패키지를 미리 받아 옮깁니다.

**인터넷 PC에서:**

```powershell
cd backend
python -m pip download -r requirements.txt -d .\offline-wheels
cd ..\frontend
npm ci
Compress-Archive -Path node_modules -DestinationPath ..\offline-node_modules.zip
```

**운영 PC에서:** `backend\offline-wheels` 폴더와 `offline-node_modules.zip`을 복사한 뒤

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\offline-wheels -r requirements.txt
cd ..
Expand-Archive .\offline-node_modules.zip -DestinationPath .\frontend
.\install.ps1 -SkipFrontend
cd frontend
npm run build
```

---

## 7. 백업과 복구

```powershell
.\backup.ps1
```

```
backup\soc_handover_20260916_180500.dump
backup\soc_handover_20260916_180500_attachments.zip
```

- 기본 보존기간 30일 (`-KeepDays 60`으로 변경)
- 네트워크 드라이브에 사본 보관: `.\backup.ps1 -Destination \\nas\soc-backup`
- **백업 파일에는 인수인계 전문이 들어 있습니다.** 폴더 접근 권한을 관리자만으로 제한하십시오.

매일 자동 백업(작업 스케줄러, 관리자 권한):

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\backup.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 03:00
Register-ScheduledTask -TaskName "SOC-Handover-Backup" -Action $action -Trigger $trigger -RunLevel Highest
```

복구:

```powershell
.\restore.ps1
```

목록에서 백업을 고르고 `RESTORE`를 입력하면 복구합니다. 복구 직전 현재 상태를 `pre_restore_*`로 한 벌 남깁니다.

---

## 8. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| `이 시스템에서 스크립트를 실행할 수 없으므로` | 1단계의 `Set-ExecutionPolicy -Scope Process` 실행 |
| `Python 3.12 를 찾지 못했습니다` | Python 설치 시 "Add to PATH" 체크, 또는 `.env`에 `PYTHON_EXE=` 지정 |
| `포트 8080 가 이미 사용 중입니다` | `.env`의 `APP_PORT`를 8081 등으로 변경 후 `.\start.ps1` |
| 기동은 됐는데 화면이 안 나옴 | 프론트 빌드 누락. `.\install.ps1` 재실행 또는 `frontend`에서 `npm run build` |
| `마이그레이션 실패` | `.env`의 `DATABASE_URL` 확인, PostgreSQL 서비스 실행 여부 확인 |
| 화면 상단에 "개발용 DB" 경고 | SQLite로 동작 중. 운영이라면 3단계로 PostgreSQL 전환 |
| 로그인 후 바로 비밀번호 변경 화면 | 정상 동작(초기 비밀번호 강제 변경) |
| 계정이 잠김 | 5회 연속 실패 시 5분 잠금. 관리자가 `관리자 > 사용자`에서 비밀번호 재설정 가능 |
| 한글이 깨져 보임 | PowerShell에서 `chcp 65001` 실행 후 재시도 |

로그 위치:

```
logs\app.log          애플리케이션 로그
logs\error.log        오류만
logs\uvicorn.err.log  기동 실패 원인
```

---

## 9. 다른 PC로 옮기기 (이전/移設)

### 9.1 옮길 것과 옮기지 말 것

| 항목 | 이전 | 이유 |
|---|---|---|
| `backend\app`, `frontend\src`, `docs`, `*.ps1` | ✅ | 소스 |
| `backend\.venv` | ❌ | 가상환경에 **절대경로가 박혀 있어** 다른 PC에서 동작하지 않음 |
| `frontend\node_modules` | ❌ | pnpm 링크 구조라 복사하면 깨짐 |
| `.env` | ❌(원칙) | `SECRET_KEY`·DB 비밀번호. 대상 PC에서 새로 생성 |
| `data\`, `backup\` | 선택 | 실제 인수인계 데이터. 옮기려면 백업/복구 사용 |
| `logs\`, `run\` | ❌ | 런타임 산출물 |

> `.env`의 `SECRET_KEY`를 그대로 옮기면 **이전 PC에서 발급된 세션 쿠키가 새 PC에서도 유효**해집니다.
> 장비를 교체·폐기하는 경우라면 새로 생성(기본 동작)하는 편이 안전합니다.

### 9.2 패키지 만들기 — `package.ps1`

현재 PC에서 실행하면 옮길 파일만 골라 zip으로 묶어 줍니다.

```powershell
.\package.ps1
```

```powershell
.\package.ps1 -Offline -IncludeData -OutDir D:\usb
```

| 옵션 | 효과 |
|---|---|
| (없음) | 소스만. **약 0.2MB.** 대상 PC에 인터넷 + Node.js 필요 |
| `-Offline` | Python wheel 48개 + **빌드된 UI** 포함. **약 12MB.** 대상 PC에 **인터넷·Node.js 불필요**(Python만 필요) |
| `-IncludeData` | 현재 데이터를 백업해 `_restore\` 에 포함 |
| `-OutDir` | 저장 위치(기본: 프로젝트 상위 폴더) |

zip 안에 `_이전방법.txt`가 함께 들어가므로, 대상 PC 담당자는 그 파일만 보면 됩니다.

### 9.3 대상 PC에서

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\install.ps1
```

```powershell
.\start.ps1
```

`install.ps1`은 `backend\offline-wheels`가 있으면 **자동으로 오프라인 설치**(`--no-index`)로 전환하고,
Node.js가 없어도 `frontend\dist`가 있으면 사전 빌드된 UI를 그대로 사용합니다.
관리자 비밀번호는 대상 PC에서 새로 입력합니다.

데이터도 함께 옮겼다면:

```powershell
.\restore.ps1 -File .\_restore\soc_handover_20260916_213000.db
```

복구하면 **이전 PC의 계정·비밀번호가 그대로 사용**되며, 설치 중 만든 새 관리자 계정은 대체됩니다.

### 9.4 운영 PC(PostgreSQL)로 옮길 때

1. 대상 PC에 PostgreSQL 16 설치 (3장)
2. `.env`의 `DATABASE_URL`을 PostgreSQL로 수정
3. `.\install.ps1` 다시 실행 → 스키마가 PostgreSQL에 생성됨
4. 기존 데이터 이전이 필요하면:
   - 이전 PC도 PostgreSQL이었다면 `.\backup.ps1`(`.dump`) → `.\restore.ps1`
   - 이전 PC가 SQLite였다면 데이터 이관 스크립트가 필요합니다(Phase 4의 Excel Export/Import로도 가능)

### 9.5 폴더째 복사하는 경우 (스크립트를 쓰지 않을 때)

USB나 공유폴더로 폴더를 통째로 복사한다면 아래 4개는 **반드시 지우고** 복사하십시오.

```powershell
Remove-Item .\backend\.venv, .\frontend\node_modules, .\logs, .\run -Recurse -Force
Remove-Item .\.env -Force
```

복사 후 대상 PC에서 `.\install.ps1`을 실행하면 지운 항목이 새로 만들어집니다.

---

## 10. OneDrive 동기화 폴더에 설치한 경우

`node_modules`, `.venv`, `data`, `backup`, `logs`는 동기화 대상에서 제외하십시오. 동기화 충돌과 지연의 원인이 됩니다.

- 탐색기에서 해당 폴더 우클릭 → **"이 장치에서 항상 유지"를 해제**하거나
- `.env`에서 데이터 경로를 동기화 폴더 밖으로 지정합니다.

```
DATA_DIR=D:\soc-handover-data
BACKUP_DIR=D:\soc-handover-backup
```
