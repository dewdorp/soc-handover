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
- **`.env` 도 한 벌 따로 보관하십시오.** 비밀번호 보관(장비 계정) 기능의 암호화 키(`VAULT_KEY`)가
  거기에만 있습니다. DB 백업에는 암호문만 들어가므로, 키를 잃으면 보관된 비밀번호는 되살릴 수 없습니다
  (인수인계 · 할일 등 나머지 데이터는 백업만으로 복구됩니다).

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

## 4. 업그레이드 · 패치

받는 파일이 두 가지입니다. 보통은 **패치**면 충분합니다.

| | 패치 `-patch.zip` | 전체 `-offline.zip` |
|---|---|---|
| 크기 | 수 MB | 약 110MB |
| 바꾸는 것 | 앱 · 화면 · 운영 스크립트 · 문서 | 위 + Python · PostgreSQL |
| 실행 | `UPDATE.cmd` | `INSTALL.cmd` |
| 쓸 수 없는 때 | 라이브러리가 바뀐 버전(패치 프로그램이 확인하고 안내) | — |
| 처음 설치 | 불가 | 가능 |

### 4.1 패치 (앱만)

1. 패치 zip 을 풀고 `UPDATE.cmd` 를 실행합니다(서비스 모드면 권한 요청 → [예]).
2. 지금 버전과 새 버전을 보여 주고 `Y` 를 받으면 진행합니다:
   패치 파일 검사 → 앱 중지(DB 는 켜 둠) → DB 백업 → 지금 파일을 `rollback\` 에 보관 →
   파일 교체 → DB 구조 갱신 → 시작 → 응답 확인.
3. 실패하면 **보관해 둔 파일로 자동으로 되돌리고** 앱을 다시 띄웁니다.
   DB 구조가 이미 바뀐 경우에는 화면에 되돌릴 백업 파일 경로를 알려 줍니다(`restore.cmd`).

```
UPDATE.cmd                              설치 폴더를 알아서 찾습니다
UPDATE.cmd -InstallDir D:\SOC-Handover  못 찾을 때 직접 지정
```

- 설정(`.env`) · 데이터 · 첨부 · 백업 · 로그 · 서비스 · 방화벽 등록은 건드리지 않습니다.
- 보관본은 설치 폴더의 `rollback\<이전버전>_<날짜시각>\` 에 최근 3개만 남습니다(`-KeepRollback` 으로 조정).
- 패치를 마치면 브라우저에서 한 번 새로고침(Ctrl+F5) 하십시오.

### 4.2 전체 업그레이드

1. 새 버전 zip 을 풀고 `INSTALL.cmd` 를 실행합니다.
2. 설치 프로그램이 기존 설치를 찾아 **업그레이드**합니다: 앱 중지 → DB 백업 → 파일 교체 → DB 구조 갱신 → 재시작.
3. 데이터 · 설정(`.env`) · 포트는 그대로입니다.

업그레이드 전 백업이 실패하면 설치를 멈추고 기존 설치를 건드리지 않습니다.

### 4.3 설치 · 패치 뒤 점검 (1.3.0~)

설치나 패치가 끝나면 한 번 돌려 봅니다. **읽기만 하며** 아무것도 만들거나 지우지 않습니다.

```
cd C:\SOC-Handover
runtime\python\python.exe scripts\verify_install.py http://localhost:8080 admin
```

비밀번호는 세 번째 인자로 넘깁니다(화면에 남으므로 공용 PC 에서는 주의). 보는 것:

| 줄 | 뜻 |
|---|---|
| 열람 그룹이 있다 / '미분류' 말고 실제 그룹이 있다 | 그룹을 아직 안 나눴으면 알려 줍니다 |
| 미분류로 남은 자료가 없다 | 남아 있으면 관리자 → 열람 그룹에서 옮기십시오 |
| 32일 동안 매일 주간 1조 · 야간 1조 | 조의 주기 위치가 어긋났는지 |
| 네 조에 사람이 들어 있다 | 조 편성을 안 했으면 알려 줍니다 |
| 마감 점검 숫자 = 바구니 · 확인함 | 대시보드 숫자가 목록과 맞는지 |
| RAG 사례에 비밀번호 · 개인 메모가 없다 | 넣지 말아야 할 것이 섞였는지 |

**다른 그룹이 실제로 막히는지**는 그 그룹에 속하지 않은 계정으로 로그인해 확인하십시오
(이 스크립트는 관리자 한 계정으로만 봅니다).

### 4.4 1.3.1 패치 — 올린 뒤에 해야 할 일

패치 자체는 **공개 범위를 바꾸지 않습니다.** 과거 자료가 저절로 전체 공개가 되는 일은
없으니, 패치를 적용한 뒤 아래를 순서대로 보십시오.

#### ① 그대로 둘지, 전체 공개로 바꿀지 정한다

1.3.1 부터 **새로 쓰는** 인수인계는 그룹을 고르지 않으면 전체 공개입니다.
전에 쌓인 '그룹 미지정' 자료는 그대로 그룹 제한으로 남아 있습니다.

바꾸려면 **관리자 → 열람 그룹 → ‘과거 그룹 미지정 자료 전체 공개 전환’** 에서:

1. 건수와 **공개될 자료 목록**을 눈으로 확인합니다. 과거 인계 본문에 계정 ·
   장비 정보 · 고객 정보가 적혀 있을 수 있습니다.
2. 경고를 읽습니다. 전환하면 **로그인한 모든 활성 계정**이 읽습니다 —
   외주 · 협력사 계정이 포함돼 있는지 먼저 확인하십시오.
3. `backup.cmd` 로 DB 백업을 받습니다.
4. 확인 문구 `전체공개로 전환` 을 직접 입력하고 백업 확인에 동의합니다.
5. 잘못 바꿨으면 같은 화면의 **되돌리기**로 묶음 단위로 되돌립니다.

바꾸지 않아도 됩니다. 그대로 두면 지금까지와 똑같이 보입니다.

#### ② 비밀번호 일괄 열람 시간을 정한다

**설정 → 비밀번호**

| 설정 | 기본 | 범위 |
|---|---|---|
| 비밀번호 열람 시간 | 5분 | 1~10분 |
| 열람 세션 최대 유지시간 | 15분 | 5~15분 (보안 상한 — 더 길게는 설정할 수 없습니다) |

#### ③ 감사로그 열람 기록을 켤지 정한다

**설정 → 감사로그 → ‘단순 인수인계 열람 기록’** 은 기본 **꺼짐**입니다.
로그인 실패 · 계정 잠금 · 권한 변경 · 내보내기 · 비밀번호 열람 · 설정 변경 ·
백업/복구는 **설정과 무관하게 계속 기록**됩니다. 막힌 열람(남의 그룹 자료를 번호로
찔러 본 흔적)도 계속 남습니다. **기존 감사로그는 지워지지 않습니다.**

점검 감사 때 열람 기록이 필요하면 그 기간만 켜 두십시오(켜고 끈 것도 감사에 남습니다).

#### ④ 정기 점검을 등록한다

점검 항목은 **일정**으로 등록합니다. 새 메뉴는 없습니다.

1. **일정 → 새 일정** → 종류를 **‘점검’** 으로.
2. 반복을 **매일 · 매주 · 매월**로 지정하고, 담당자를 정합니다(비우면 근무자 누구나 완료).
3. 그러면 **대시보드 ‘오늘 점검’** 과 **일정 → 정기 점검** 탭에 그 날 회차가 나옵니다.
   동그라미를 눌러 완료하면 누가 언제 했는지 남고, 교대 마감 점검의 ‘오늘 점검 미완료’
   숫자가 줄어듭니다.

예: `근무 시작 장비 상태 점검`(매일), `SIEM·SOAR·NDR 수집 상태 확인`(매일),
`탐지·차단 정책 이상 점검`(매주 월), `A보안 월간 정기 점검`(매월 1일).

점검 **방법**은 운영 지식에 '점검 체크리스트' 분류로 적어 두고, 일정 설명에 그 문서
제목을 적어 두면 야간 근무자가 한 번에 찾습니다.

#### ⑤ 운영 지식에 절차를 옮긴다

**운영 지식 → 새 문서 → ‘표준 양식 넣기’** 가 7절 뼈대를 넣어 줍니다
(목적·범위 / 탐지·확인 기준 / 분석 절차 / 조치 방법 / 보고·전파 기준 / 후속 확인 / 관련 문서).

- 공개 범위는 기본 **전체 공유**입니다. 외주에 보이면 안 되는 절차는 **그룹 선택**으로
  바꾸십시오. **첨부도 문서와 같은 권한을 따릅니다**(문서를 못 보면 파일도 못 받습니다).
- 고칠 때 **수정 사유**를 적으면 개정 이력에 남고, 나중에 판을 나란히 비교하거나
  옛 판으로 되돌릴 수 있습니다(되돌림도 새 판으로 쌓입니다).
- **재검토 예정일**을 넣어 두면 기한이 지난 문서를 목록에서 걸러 볼 수 있습니다.

#### ⑥ 점검 스크립트를 한 번 돌린다

4.3 과 같습니다. 1.3.1 에서는 아래가 더 보입니다.

```
cd C:\SOC-Handover
runtime\python\python.exe scripts\verify_install.py http://localhost:8080 admin
```

| 줄 | 뜻 |
|---|---|
| 그룹 미지정 과거 자료 N건(전환 대기) | 전환할지 말지 정하지 않은 자료가 남아 있습니다 |
| 금고 열람 시간 5분 / 상한 15분 | 설정이 상한 안에 있는지 |
| 단순 열람 기록 꺼짐 | 감사 소음 설정 상태 |
| 오늘 점검 N건 중 M건 완료 | 정기 점검이 등록돼 돌고 있는지 |
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

### 5-1. 로그인이 자주 막힌다면 (1.3.0~)

로그인은 **5분에 20회**(IP 기준)로 막습니다 — 무차별 대입을 막는 값입니다. 한 PC 를
여럿이 돌려 쓰는 교대 콘솔에서 교대 시각에 모자라면 `.env` 를 열어 올립니다.

```
RATE_LIMIT_LOGIN_PER_5MIN=60
```

바꾼 뒤 `stop.cmd` → `start.cmd`. 올릴 때는 계정 잠금(연속 실패 시 잠금)이 켜져 있는지
함께 확인하십시오 — 둘 중 하나는 남아 있어야 합니다.

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
| `logs\patch-migrate.err.log` | 패치의 DB 구조 갱신 기록(`%TEMP%\soc-handover-update-*.log` 에 전체 진행) |

로그에는 비밀번호 · 토큰이 남지 않습니다. 오류 화면의 `요청 ID` 로 `logs\app.log` 에서 찾을 수 있습니다.

---

## 9. 보안 수칙

- 설치 폴더의 `data` · `backup` · `logs` · `.env` 는 관리자와 설치한 사용자만 읽을 수 있게 설정되어 있습니다. 권한을 넓히지 마십시오.
- 백업 파일에는 인수인계 전문이 들어 있습니다. 외부 저장장치로 옮길 때 취급에 주의하십시오.
- 공용 네트워크로 분류된 PC 에서는 방화벽을 공용 프로필에도 열게 됩니다. 가능하면 네트워크를 '개인' 또는 도메인으로 두십시오.
- HTTPS 가 필요하면 사내 인증서를 발급받아 5장의 `SSL_CERTFILE` · `SSL_KEYFILE` 을 설정하십시오.
