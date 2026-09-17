<#
.SYNOPSIS
    다른 PC로 옮기기 위한 배포 패키지(zip) 생성

.DESCRIPTION
    소스만 담은 가벼운 패키지, 또는 인터넷이 없는 PC에서도 설치 가능한
    오프라인 패키지를 만듭니다.

    옮기면 안 되는 것은 자동으로 제외합니다.
      · backend\.venv        가상환경(절대경로가 박혀 있어 다른 PC에서 동작하지 않음)
      · frontend\node_modules  pnpm 심볼릭 링크 구조라 복사해도 깨짐
      · .env                 SECRET_KEY·DB 비밀번호. 대상 PC에서 새로 생성해야 함
      · logs, run            런타임 산출물

.PARAMETER Offline
    대상 PC에 인터넷이 없을 때 사용합니다.
    · Python 패키지(wheel)를 backend\offline-wheels 로 미리 내려받아 포함
    · 이미 빌드된 frontend\dist 를 포함 → 대상 PC에 Node.js 가 필요 없습니다

.PARAMETER IncludeData
    현재 데이터(인수인계 내용)를 함께 옮깁니다. 최신 백업을 새로 만들어 포함합니다.
    ※ 인수인계 전문이 들어가므로 취급에 주의하십시오.

.PARAMETER OutDir
    패키지를 만들 위치. 기본값은 프로젝트 상위 폴더.

.EXAMPLE
    .\package.ps1
    소스만 담은 패키지(대상 PC에 인터넷 필요)

.EXAMPLE
    .\package.ps1 -Offline -IncludeData -OutDir D:\usb
    인터넷 없는 PC용 + 현재 데이터 포함
#>
[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$IncludeData,
    [string]$OutDir
)

. "$PSScriptRoot\scripts\common.ps1"
Import-DotEnv | Out-Null

if (-not $OutDir) { $OutDir = Split-Path -Parent $Root }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$name = "soc-handover_$stamp" + $(if ($Offline) { '_offline' } else { '' })
$stage = Join-Path ([System.IO.Path]::GetTempPath()) $name
$zipPath = Join-Path $OutDir "$name.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

Write-Host '==============================================' -ForegroundColor White
Write-Host ' 배포 패키지 생성' -ForegroundColor White
Write-Host '==============================================' -ForegroundColor White

# ---------------------------------------------------------------- 1. 소스 복사
Write-Step '소스 복사'

$exclude = @(
    '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache',
    'logs', 'run', 'data', 'backup', '.git', 'offline-wheels'
)
$excludeFiles = @('.env', '*.pyc', '*.db', '*.db-wal', '*.db-shm', 'desktop.ini', 'Thumbs.db')

# robocopy 는 대용량 폴더 제외가 빠르고 안정적이다.
$roboArgs = @(
    $Root, $stage, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1',
    '/XD'
) + $exclude + @('/XF') + $excludeFiles

$null = & robocopy @roboArgs
# robocopy 종료코드 0~7 은 정상(8 이상이 실패)
if ($LASTEXITCODE -ge 8) { Write-Err "소스 복사 실패 (robocopy $LASTEXITCODE)"; exit 1 }
$global:LASTEXITCODE = 0

$copied = (Get-ChildItem $stage -Recurse -File).Count
Write-Ok "$copied 개 파일 복사"

# dist 는 오프라인 패키지에서만 포함한다(그 외에는 대상 PC에서 빌드)
$stageDist = Join-Path $stage 'frontend\dist'
if (-not $Offline -and (Test-Path $stageDist)) {
    Remove-Item $stageDist -Recurse -Force
    Write-Ok 'frontend\dist 제외 (대상 PC에서 빌드)'
}

# ---------------------------------------------------------------- 2. 오프라인 자산
if ($Offline) {
    Write-Step '오프라인 설치용 Python 패키지 내려받기'

    if (-not (Test-Path $VenvPython)) {
        Write-Err '가상환경이 없습니다. 먼저 .\install.ps1 을 실행하십시오.'
        exit 1
    }

    $wheelDir = Join-Path $stage 'backend\offline-wheels'
    New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null

    & $VenvPython -m pip download --disable-pip-version-check -q `
        -r (Join-Path $BackendDir 'requirements.txt') -d $wheelDir
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'wheel 내려받기 실패 (이 PC의 인터넷 연결을 확인하십시오)'
        exit 1
    }
    $wheels = Get-ChildItem $wheelDir -File
    $wheelMb = [math]::Round(($wheels | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Ok "$($wheels.Count) 개 패키지 (${wheelMb}MB)"

    Write-Step '프론트엔드 빌드 결과 포함'
    $srcDist = Join-Path $FrontendDir 'dist\index.html'
    if (-not (Test-Path $srcDist)) {
        Write-Warn2 'frontend\dist 가 없습니다. 먼저 빌드하십시오(.\install.ps1).'
        Write-Warn2 '→ 대상 PC에 Node.js 설치가 필요해집니다.'
    } else {
        Write-Ok "사전 빌드된 UI 포함 (대상 PC에 Node.js 불필요)"
    }
}

# ---------------------------------------------------------------- 3. 데이터
if ($IncludeData) {
    Write-Step '데이터 백업 포함'
    & "$PSScriptRoot\backup.ps1" -KeepDays 3650 | Out-Null

    $latest = Get-ChildItem $BackupDir -Filter 'soc_handover_*' |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Write-Err '백업 파일을 만들지 못했습니다.'; exit 1 }

    $dataDir = Join-Path $stage '_restore'
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    Copy-Item $latest.FullName $dataDir

    $att = Get-ChildItem $BackupDir -Filter "$($latest.BaseName)_attachments.zip" -ErrorAction SilentlyContinue
    if ($att) { Copy-Item $att.FullName $dataDir }

    Write-Ok "$($latest.Name) 포함 ($([math]::Round($latest.Length/1MB,2))MB)"
    Write-Warn2 '이 패키지에는 인수인계 전문이 들어 있습니다. 전달 경로에 주의하십시오.'
}

# ---------------------------------------------------------------- 4. 안내문
# 주의: here-string 안에 here-string 을 중첩할 수 없으므로 조각을 미리 만들어 둔다.
if ($Offline) {
    $depsNote = @(
        '   - 인터넷이 없어도 backend\offline-wheels 로 설치됩니다.',
        '   - UI 는 이미 빌드되어 있어 Node.js 가 필요 없습니다.'
    ) -join "`r`n"
} else {
    $depsNote = @(
        '   - 인터넷이 필요합니다(pip / npm 내려받기).',
        '   - UI 빌드를 위해 Node.js 20 이상이 필요합니다.'
    ) -join "`r`n"
}

if ($IncludeData) {
    $dataNote = @(
        '4) 기존 데이터 복구:',
        '',
        "     .\restore.ps1 -File .\_restore\$($latest.Name)",
        '',
        '   확인 문구로 RESTORE 를 입력하면 복구됩니다.',
        '   ※ 복구 후에는 이전 PC의 계정/비밀번호가 그대로 사용됩니다.',
        '      (install.ps1 에서 만든 새 관리자 계정은 덮어쓰기됩니다)'
    ) -join "`r`n"
} else {
    $dataNote = '4) 데이터는 비어 있습니다. 관리자 > 관계사 등록부터 시작하십시오.'
}

$kindNote = if ($Offline) { '오프라인(인터넷 없는 PC용)' } else { '소스만(대상 PC에 인터넷 필요)' }
$dataKind = if ($IncludeData) { '포함 (_restore 폴더)' } else { '미포함 — 새로 시작' }

$readme = @"
SOC 인수인계 플랫폼 — 이전(移設) 패키지
=========================================
만든 날짜 : $(Get-Date -Format 'yyyy-MM-dd HH:mm')
만든 PC   : $env:COMPUTERNAME
형태      : $kindNote
데이터    : $dataKind

대상 PC에서 할 일
-----------------
1) 이 폴더를 원하는 위치에 압축 해제합니다. 예: C:\soc-handover
   ※ OneDrive 동기화 폴더는 피하는 것을 권장합니다.

2) PowerShell 을 열고 해당 폴더로 이동한 뒤:

     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
     .\install.ps1

   - Python 3.12 가 필요합니다(없으면 설치 안내가 나옵니다).
$depsNote
   - 설치 중 관리자 비밀번호를 새로 입력합니다.

3) 기동:

     .\start.ps1

   브라우저에서 http://localhost:8080/ 접속

$dataNote

포함되지 않은 것 (의도적으로 제외)
----------------------------------
  backend\.venv           가상환경 — 절대경로가 박혀 있어 이전 불가. install.ps1 이 새로 만듭니다.
  frontend\node_modules   pnpm 링크 구조 — 복사 시 깨짐. install.ps1 이 새로 받습니다.
  .env                    SECRET_KEY / DB 비밀번호 — 대상 PC에서 새로 생성됩니다.
                          (기존 SECRET_KEY 를 옮기면 이전 PC의 세션 쿠키가 그대로 유효해집니다)
  logs, run               런타임 산출물

운영 PC 라면
------------
  PostgreSQL 16 을 먼저 설치하고 .env 의 DATABASE_URL 을 바꾼 뒤 install.ps1 을 다시 실행하십시오.
  자세한 내용: INSTALL_WINDOWS.md 3장
"@

Set-Content -Path (Join-Path $stage '_이전방법.txt') -Value $readme -Encoding UTF8
Write-Ok '_이전방법.txt 생성'

# ---------------------------------------------------------------- 5. 압축
Write-Step '압축'
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' 패키지 생성 완료' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ''
Write-Host "  파일 : $zipPath"
Write-Host "  크기 : ${sizeMb}MB"
Write-Host ''
Write-Host '  USB/공유폴더로 옮긴 뒤, 대상 PC에서 압축을 풀고'
Write-Host '  _이전방법.txt 의 순서대로 진행하십시오.'
Write-Host ''
