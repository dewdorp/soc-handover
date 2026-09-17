<#
.SYNOPSIS
    백업으로부터 복구

.DESCRIPTION
    현재 데이터를 백업 시점으로 되돌립니다. 되돌릴 수 없는 작업이므로 확인 문구 입력을 요구합니다.
    복구 전에 현재 상태를 안전 백업(pre-restore)으로 한 벌 남깁니다.

.PARAMETER File
    복구할 백업 파일. 생략하면 목록에서 선택합니다.

.PARAMETER Yes
    확인 문구 입력을 생략합니다(무인 실행용). 신중히 사용하십시오.

.EXAMPLE
    .\restore.ps1
    .\restore.ps1 -File .\backup\soc_handover_20260916_180500.db
#>
[CmdletBinding()]
param(
    [string]$File,
    [switch]$Yes
)

. "$PSScriptRoot\scripts\common.ps1"
Import-DotEnv | Out-Null

# ---------------------------------------------------------------- 대상 선택
if (-not $File) {
    $candidates = Get-ChildItem $BackupDir -Filter 'soc_handover_*' |
                  Where-Object { $_.Extension -in @('.dump', '.db') } |
                  Sort-Object LastWriteTime -Descending
    if (-not $candidates) { Write-Err "백업 파일이 없습니다: $BackupDir"; exit 1 }

    Write-Host ''
    Write-Host '복구할 백업을 선택하십시오:' -ForegroundColor White
    for ($i = 0; $i -lt $candidates.Count; $i++) {
        $c = $candidates[$i]
        Write-Host ("  [{0}] {1}  ({2}MB, {3})" -f ($i + 1), $c.Name,
            [math]::Round($c.Length / 1MB, 2), $c.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))
    }
    $sel = Read-Host "`n번호"
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $candidates.Count) {
        Write-Err '올바른 번호가 아닙니다.'; exit 1
    }
    $File = $candidates[$idx - 1].FullName
}

if (-not (Test-Path $File)) { Write-Err "파일을 찾을 수 없습니다: $File"; exit 1 }
$File = (Resolve-Path $File).Path

# ---------------------------------------------------------------- 확인
Write-Host ''
Write-Host '───────────────────────────────────────────────' -ForegroundColor Yellow
Write-Host ' 경고: 현재 데이터베이스의 내용이 모두 대체됩니다.' -ForegroundColor Yellow
Write-Host "  대상 백업 : $(Split-Path -Leaf $File)"
Write-Host "  현재 DB   : $(Get-EnvValue 'DATABASE_URL')"
Write-Host '───────────────────────────────────────────────' -ForegroundColor Yellow

if (-not $Yes) {
    $answer = Read-Host '계속하려면 RESTORE 를 입력하십시오'
    if ($answer -ne 'RESTORE') { Write-Host '취소되었습니다.'; exit 0 }
}

# ---------------------------------------------------------------- 서비스 중지
$proc = Get-AppProcess
$wasRunning = $false
if ($proc) {
    $wasRunning = $true
    Write-Step '서비스 중지'
    & "$PSScriptRoot\stop.ps1" | Out-Null
}

# ---------------------------------------------------------------- 안전 백업
Write-Step '현재 상태 안전 백업'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if (Test-IsPostgres) {
    & "$PSScriptRoot\backup.ps1" -KeepDays 3650 | Out-Null
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    if (Test-Path $dbFile) {
        Copy-Item $dbFile (Join-Path $BackupDir "pre_restore_$stamp.db") -Force
    }
}
Write-Ok '안전 백업 완료'

# ---------------------------------------------------------------- 복구
Write-Step '복구 수행'
if (Test-IsPostgres) {
    $pgRestore = Get-Command pg_restore -ErrorAction SilentlyContinue
    if (-not $pgRestore) {
        foreach ($p in @('C:\Program Files\PostgreSQL\17\bin', 'C:\Program Files\PostgreSQL\16\bin',
                         'C:\Program Files\PostgreSQL\15\bin')) {
            if (Test-Path (Join-Path $p 'pg_restore.exe')) { $pgRestore = Join-Path $p 'pg_restore.exe'; break }
        }
    } else { $pgRestore = $pgRestore.Source }
    if (-not $pgRestore) { Write-Err 'pg_restore 를 찾지 못했습니다.'; exit 1 }

    $libpq = (Get-EnvValue 'DATABASE_URL') -replace '^postgresql\+\w+://', 'postgresql://'
    & $pgRestore --clean --if-exists --no-owner --dbname $libpq $File
    if ($LASTEXITCODE -ne 0) { Write-Err 'pg_restore 실패'; exit 1 }
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    foreach ($sfx in @('', '-wal', '-shm')) {
        $p = "$dbFile$sfx"
        if (Test-Path $p) { Remove-Item $p -Force }
    }
    Copy-Item $File $dbFile -Force
}
Write-Ok '복구 완료'

# ---------------------------------------------------------------- 스키마 최신화
Write-Step '스키마 확인'
Push-Location $BackendDir
try {
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Write-Warn2 '마이그레이션 적용 실패 — 수동 확인이 필요합니다.' }
    else { Write-Ok '스키마 최신 상태' }
} finally { Pop-Location }

# ---------------------------------------------------------------- 재기동
if ($wasRunning) {
    Write-Step '서비스 재기동'
    & "$PSScriptRoot\start.ps1"
    Write-SystemAudit 'RESTORE' @{ file = (Split-Path -Leaf $File) } | Out-Null
} else {
    Write-Host ''
    Write-Host '  서비스는 중지 상태입니다. .\start.ps1 로 기동하십시오.'
}
