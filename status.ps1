<#
.SYNOPSIS
    SOC 인수인계 플랫폼 상태 점검
.DESCRIPTION
    프로세스 · 포트 · DB 연결 · 마이그레이션 리비전 · 디스크 · 최근 백업을 한 화면에 보여줍니다.
#>
[CmdletBinding()]
param()

. "$PSScriptRoot\scripts\common.ps1"
Import-DotEnv | Out-Null

function Show-Line([string]$Label, [string]$Value, [string]$Color = 'White') {
    Write-Host ("  {0,-14}" -f $Label) -NoNewline
    Write-Host $Value -ForegroundColor $Color
}

Write-Host ''
Write-Host '── SOC 인수인계 플랫폼 상태 ─────────────────────────' -ForegroundColor White

# 프로세스
$proc = Get-AppProcess
if ($proc) {
    $mem = [math]::Round($proc.WorkingSet64 / 1MB, 1)
    Show-Line '프로세스' "실행 중 (PID $($proc.Id), 메모리 ${mem}MB, 시작 $($proc.StartTime.ToString('MM-dd HH:mm')))" 'Green'
} else {
    Show-Line '프로세스' '중지됨' 'Yellow'
}

# 포트
$port = Get-AppPort
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) { Show-Line '포트' "$port LISTEN" 'Green' }
else { Show-Line '포트' "$port 미사용" 'Yellow' }

# 헬스체크
$health = Test-AppHealth 3
if ($health) {
    Show-Line 'API' "$(Get-HealthUrl) → $($health.status)" 'Green'
    Show-Line 'DB 연결' "$($health.database) / $(if ($health.database_ok) {'정상'} else {'실패'})" `
        $(if ($health.database_ok) { 'Green' } else { 'Red' })
} else {
    Show-Line 'API' '응답 없음' 'Yellow'
}

# 마이그레이션 리비전
if (Test-Path $VenvPython) {
    Push-Location $BackendDir
    try {
        $rev = (& $VenvPython -c @"
from sqlalchemy import text
from app.core.db import engine
try:
    with engine.connect() as c:
        print(c.execute(text('SELECT version_num FROM alembic_version')).scalar() or '없음')
except Exception as e:
    print('확인 실패')
"@) 2>$null
        Show-Line '마이그레이션' ($rev | Select-Object -Last 1)
    } finally { Pop-Location }
} else {
    Show-Line '설치 상태' '가상환경 없음 — install.ps1 필요' 'Yellow'
}

# 프론트엔드
$dist = Join-Path $FrontendDir 'dist\index.html'
if (Test-Path $dist) {
    Show-Line '프론트엔드' "빌드됨 ($((Get-Item $dist).LastWriteTime.ToString('yyyy-MM-dd HH:mm')))" 'Green'
} else {
    Show-Line '프론트엔드' '빌드 없음 (API 전용 동작)' 'Yellow'
}

# DB 크기
if (Test-IsPostgres) {
    Show-Line '데이터베이스' 'PostgreSQL' 'Green'
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    if (Test-Path $dbFile) {
        $size = [math]::Round((Get-Item $dbFile).Length / 1MB, 2)
        Show-Line '데이터베이스' "SQLite (${size}MB) — 개발/평가용" 'Yellow'
    } else {
        Show-Line '데이터베이스' 'SQLite 파일 없음' 'Yellow'
    }
}

# 첨부/디스크
if (Test-Path (Join-Path $DataDir 'attachments')) {
    $att = Get-ChildItem (Join-Path $DataDir 'attachments') -Recurse -File -ErrorAction SilentlyContinue
    $attSize = if ($att) { [math]::Round(($att | Measure-Object Length -Sum).Sum / 1MB, 1) } else { 0 }
    Show-Line '첨부파일' "$($att.Count)개 (${attSize}MB)"
}

$drive = Get-PSDrive -Name ($Root.Substring(0, 1)) -ErrorAction SilentlyContinue
if ($drive) {
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    Show-Line '디스크 여유' "${freeGb}GB" $(if ($freeGb -lt 5) { 'Red' } else { 'White' })
}

# 최근 백업
$last = Get-ChildItem $BackupDir -Filter 'soc_handover_*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($last) {
    $age = (Get-Date) - $last.LastWriteTime
    Show-Line '최근 백업' "$($last.Name) ($([int]$age.TotalHours)시간 전)" `
        $(if ($age.TotalDays -gt 2) { 'Yellow' } else { 'Green' })
} else {
    Show-Line '최근 백업' '없음 — .\backup.ps1 실행 권장' 'Yellow'
}

# 최근 오류 로그
$errLog = Join-Path $LogDir 'error.log'
if (Test-Path $errLog) {
    $errCount = @(Select-String -Path $errLog -Pattern 'ERROR' -ErrorAction SilentlyContinue).Count
    Show-Line '오류 로그' "$errCount건 ($errLog)" $(if ($errCount -gt 0) { 'Yellow' } else { 'White' })
}

Write-Host '─────────────────────────────────────────────────────' -ForegroundColor White
Write-Host ''
