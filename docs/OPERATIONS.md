# OPERATIONS.md — 운영 안내 (설치 PC 담당자용)

오프라인 설치 패키지(INSTALL.cmd)로 설치한 PC 기준입니다. 설치 폴더는 기본 `C:\SOC-Handover` 입니다.
이 문서의 `.cmd` 는 설치 폴더에 있는 파일이고, 더블클릭하면 됩니다.

---

## 1. 구성 한눈에

```
브라우저(여러 PC) ──http://서버PC:8080──▶ 앱(Python · uvicorn)  ──127.0.0.1:5432──▶ DB(PostgreSQL 16)
                                           C:\SOC-Handover\runtime\python          C:\SOC-Handover\runtime\pgsql
                                                                                    데이터: data\pgdata
```

| 항목 | 위치 · 이름 |
|---|---|
| 설치 폴더 | `C:\SOC-Handover` |
| 설정 | `.env` (포트 · DB 비밀번호 · 비밀키 — 관리자와 설치한 사용자만 읽을 수 있음) |
| DB 데이터 | `data\pgdata` |
| 첨부 파일 | `data\attachments` |
| 백업 | `backup\` (매일 03:00, 30일 보관) |
| 로그 | `logs\` (아래 8장) |
| 앱 자동 시작 | 작업 스케줄러 `SOC-Handover` (부팅 시, SYSTEM 계정) |
| DB 서비스 | Windows 서비스 `SOC-Handover-DB` (자동 시작, NetworkService 계정) |
| 매일 백업 | 작업 스케줄러 `SOC-Handover-Backup` (03:00, 놓치면 PC 켜진 뒤 실행) |
| 방화벽 | 인바운드 규칙 `SOC 인수인계 플랫폼 (TCP 8080)` |

DB 는 `127.0.0.1` 에서만 접속을 받습니다(다른 PC 에서 DB 로 직접 접속 불가). 다른 PC 는 8080 의 화면으로만 씁니다.

---

## 2. 켜고 끄기

### 2.1 서비스 모드 (기본 설치)

**평소에는 할 일이 없습니다.** PC 를 켜면 DB 와 앱이 자동으로 켜지고, 앱이 비정상 종료되면 실행기가 다시 띄웁니다
(곧바로 계속 죽으면 5초 → 최대 60초 간격으로 재시도, 기록은 `logs\service.log`).

| 하고 싶은 일 | 방법 |
|---|---|
| 상태 보기 | `status.cmd` |
| 끄기 | `stop.cmd` → 관리자 권한 요청 창에서 [예] |
| 다시 켜기 | `start.cmd` → [예] |
| 지금 백업 | `backup.cmd` |

- `stop.cmd` 로 끈 뒤 PC 를 재부팅하면 **다시 자동으로 켜집니다**. 계속 꺼 두려면 7장(자동 시작 끄기).
- `stop.cmd` 는 앱만 끄고 DB 서비스는 켜 둡니다. DB 까지 끄려면 관리자 PowerShell 에서
  `C:\SOC-Handover\stop.ps1 -IncludeDb`.

### 2.2 수동으로 켜고 끄기

자동 시작 없이 쓰려면 **수동 모드**로 설치합니다.

```
INSTALL.cmd -Manual
```

수동 모드는 서비스 · 예약 작업 · 방화벽을 등록하지 않습니다(관리자 권한 없이도 설치 가능).

| 하고 싶은 일 | 방법 | 설명 |
|---|---|---|
| 켜기 | `start.cmd` | DB 를 켠 뒤 앱을 켭니다. 창이 닫혀도 계속 동작합니다 |
| 끄기 | `stop.cmd` | 앱과 DB 를 함께 끕니다 |
| 상태 | `status.cmd` | |

- **로그오프하거나 PC 를 끄면 함께 꺼집니다.** PC 를 켠 뒤 다시 `start.cmd` 를 실행하십시오.
- 다른 PC 에서 접속하려면 방화벽에서 8080 포트를 열어야 합니다(관리자 PowerShell, 1회).

```powershell
New-NetFirewallRule -Name SOC-Handover-App -DisplayName "SOC 인수인계 플랫폼 (TCP 8080)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Domain,Private
```

### 2.3 PowerShell 로 직접 (두 모드 공통)

`.cmd` 파일은 아래 PowerShell 스크립트를 부르는 것뿐입니다. 서비스 모드에서는 **관리자 PowerShell** 에서 실행합니다.

```powershell
cd C:\SOC-Handover
powershell -ExecutionPolicy Bypass -File .\start.ps1
powershell -ExecutionPolicy Bypass -File .\stop.ps1
powershell -ExecutionPolicy Bypass -File .\status.ps1
```

| 옵션 | 뜻 |
|---|---|
| `start.ps1 -Foreground` | 앱을 이 창에서 실행하고 로그를 화면에 보여 줍니다(문제 확인용, Ctrl+C 로 종료). 서비스 모드면 먼저 `stop.cmd` |
| `stop.ps1 -IncludeDb` | (서비스 모드) DB 서비스까지 멈춤 |
| `stop.ps1 -KeepDb` | (수동 모드) 앱만 끄고 DB 는 켜 둠 |

### 2.4 Windows 도구로 (서비스 모드)

- DB: `services.msc` → `SOC-Handover-DB` 시작/중지
- 앱: `taskschd.msc` → 작업 스케줄러 라이브러리 → `SOC-Handover` 실행/종료
  (종료만 하면 앱 프로세스가 남을 수 있으므로 끌 때는 `stop.cmd` 를 권장)

---

## 3. 백업과 복구

### 백업

- 자동: 매일 03:00 (`SOC-Handover-Backup`). PC 가 꺼져 있었으면 켜진 뒤 실행합니다.
- 수동: `backup.cmd`
- 결과: `backup\soc_handover_YYYYMMDD_HHMMSS.dump` (DB) + `..._attachments.zip` (첨부)
- 30일 지난 백업은 지웁니다(`backup.ps1 -KeepDays 60` 으로 변경 가능).
- **백업을 다른 저장장치에도 두십시오.** 네트워크 폴더가 있으면
  `backup.ps1 -Destination \\서버\공유\soc-backup` 로 한 벌 더 복사합니다.
  (예약 작업을 바꾸려면 `taskschd.msc` 에서 `SOC-Handover-Backup` 의 인수 끝에 `-Destination ...` 추가)
- 화면 **관리자 > 백업** 에서 마지막 백업 시각과 목록을 볼 수 있습니다(26시간 넘으면 경고).

### 복구

```
restore.cmd
```

목록에서 백업 번호를 고르고 `RESTORE` 를 입력하면:
1. 앱을 멈추고 **현재 상태를 한 벌 더 백업**한 뒤
2. DB 를 백업 시점으로 되돌리고(첨부는 `..._attachments.zip` 을 `data\attachments` 에 풀어 넣음)
3. 앱을 다시 켭니다. 감사로그에 '복구'로 남습니다.

첨부 파일 복구: 필요한 경우 `backup\..._attachments.zip` 을 `data\attachments` 에 압축 풀기(덮어쓰기).

---

## 4. 업그레이드

1. 새 버전 zip 을 풀고 `INSTALL.cmd` 를 실행합니다.
2. 설치 프로그램이 기존 설치를 찾아 **업그레이드**합니다: 앱 중지 → DB 백업 → 파일 교체 → DB 구조 갱신 → 재시작.
3. 데이터 · 설정(`.env`) · 포트는 그대로입니다.

업그레이드 전 백업이 실패하면 설치를 멈추고 기존 설치를 건드리지 않습니다.

---

## 5. 설정 바꾸기

`.env` 를 메모장(관리자 권한)으로 열어 바꾼 뒤 `stop.cmd` → `start.cmd`.

| 키 | 뜻 | 바꿀 때 주의 |
|---|---|---|
| `APP_PORT` | 화면 · API 포트 | 방화벽 규칙의 포트도 바꿔야 함(관리자 PowerShell: `Set-NetFirewallRule -Name SOC-Handover-App -LocalPort 8090`) |
| `ACCESS_TOKEN_MINUTES` · `REFRESH_TOKEN_HOURS` | 로그인 유지 시간 | |
| `SSL_CERTFILE` · `SSL_KEYFILE` | HTTPS 인증서(PEM) 경로 | 설정하면 `COOKIE_SECURE=true` 도 함께 |
| `ATTACHMENT_SCAN_COMMAND` | 첨부 백신 검사 명령 | 예: `"C:\Program Files\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File {path} -DisableRemediation` |

**바꾸면 안 되는 것**: `DATABASE_URL` · `PG_*` (DB 비밀번호가 DB 안의 값과 맞아야 함), `SECRET_KEY`(바꾸면 모든 사용자가 로그아웃됨 — 유출이 의심될 때만).

업무 설정(재확인 대상 항목, 첨부 허용 확장자 · 크기, 내보내기 최대 행수 등)은 화면 **설정** 메뉴에서 바꿉니다.

---

## 6. 사용자 · 비밀번호

- 사용자 추가 · 역할 · 비활성화 · 비밀번호 초기화: 화면 **관리자 > 사용자**
- 관리자 비밀번호를 잊었을 때(다른 관리자도 없을 때) — 관리자 PowerShell:

```powershell
cd C:\SOC-Handover\backend
$env:SOC_ADMIN_PASSWORD = Read-Host "새 비밀번호"
..\runtime\python\python.exe manage.py create-admin --username admin --display-name "시스템 관리자"
Remove-Item env:SOC_ADMIN_PASSWORD
```

로그인 5회 실패 시 5분 잠깁니다(관리자가 비밀번호를 초기화하면 바로 풀림).

---

## 7. 자동 시작 끄기 · 제거

- 계속 꺼 두기(서비스 모드 유지): 관리자 PowerShell
  ```powershell
  Disable-ScheduledTask -TaskName SOC-Handover
  Set-Service -Name SOC-Handover-DB -StartupType Manual
  ```
  다시 켜려면 `Enable-ScheduledTask -TaskName SOC-Handover` · `Set-Service -Name SOC-Handover-DB -StartupType Automatic`.
- 수동 모드로 바꾸기: `uninstall.cmd`(데이터 유지) → `INSTALL.cmd -Manual` (같은 폴더)
- 제거: `uninstall.cmd` → `UNINSTALL` 입력. **데이터는 남습니다**(같은 폴더에 다시 설치하면 이어서 사용).
  데이터까지 지우려면 관리자 PowerShell 에서 `C:\SOC-Handover\uninstall.ps1 -RemoveData` (먼저 `backup` 폴더를 다른 곳에 복사).

---

## 8. 문제 해결

먼저 `status.cmd` 를 실행해 어느 부분이 멈췄는지 봅니다.

| 증상 | 확인 · 조치 |
|---|---|
| 화면이 안 열림(이 PC 에서도) | `status.cmd` → API 응답 없음이면 `start.cmd`. 그래도 안 되면 `logs\service.log` · `logs\uvicorn.err.log.prev` |
| 이 PC 에서는 되는데 다른 PC 에서 안 됨 | 방화벽 규칙 확인(`wf.msc` → 인바운드 → SOC 인수인계), 주소를 PC 이름 대신 IP 로 시도 |
| DB 응답 없음 | `services.msc` 에서 `SOC-Handover-DB` 시작. 실패하면 `data\pgdata\log\postgresql-요일.log` |
| 디스크 부족 | `status.cmd` 의 디스크 여유 확인. `backup` 폴더의 오래된 백업을 다른 곳으로 옮김 |
| 포트 충돌 | `.env` 의 `APP_PORT` 변경(5장) |
| DB 실행 파일이 "차단"됨 | Windows 11 의 Smart App Control 이 켜져 있으면 서명 없는 PostgreSQL 실행 파일을 막습니다. Windows 보안 → 앱 및 브라우저 컨트롤 → Smart App Control → 끄기(한 번 끄면 다시 켤 수 없음), 또는 사내 인증서로 `runtime\pgsql\bin\*.exe` 서명 |
| 백업이 안 됨 | `taskschd.msc` → `SOC-Handover-Backup` → 마지막 실행 결과. 수동으로 `backup.cmd` 실행해 오류 확인 |
| 느려짐 | `status.cmd` 의 DB 크기 · 메모리 확인. 화면 목록은 필터를 걸어 좁혀 보기 |

### 로그

| 파일 | 내용 |
|---|---|
| `logs\app.log` | 앱 기록(10MB × 10개 회전) |
| `logs\error.log` | 오류만 |
| `logs\service.log` | 서비스 실행기: 시작 · 비정상 종료 · 재시작 |
| `logs\uvicorn.err.log` · `.prev` | 앱이 바로 죽을 때 원인(직전 실행분은 .prev) |
| `logs\pg_ctl\` | DB 켜기 · 끄기 기록(수동 모드) |
| `data\pgdata\log\postgresql-요일.log` | DB 기록(7일 순환) |
| `logs\soc-handover-install-*.log` | 설치 · 업그레이드 기록 |

로그에는 비밀번호 · 토큰이 남지 않습니다. 오류 화면의 `요청 ID` 로 `logs\app.log` 에서 찾을 수 있습니다.

---

## 9. 보안 수칙

- 설치 폴더의 `data` · `backup` · `logs` · `.env` 는 관리자와 설치한 사용자만 읽을 수 있게 설정되어 있습니다. 권한을 넓히지 마십시오.
- 백업 파일에는 인수인계 전문이 들어 있습니다. 외부 저장장치로 옮길 때 취급에 주의하십시오.
- 공용 네트워크로 분류된 PC 에서는 방화벽을 공용 프로필에도 열게 됩니다. 가능하면 네트워크를 '개인' 또는 도메인으로 두십시오.
- HTTPS 가 필요하면 사내 인증서를 발급받아 5장의 `SSL_CERTFILE` · `SSL_KEYFILE` 을 설정하십시오.
