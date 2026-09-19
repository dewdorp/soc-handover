<#
.SYNOPSIS
    데이터베이스 + 첨부파일 백업

.DESCRIPTION
    PostgreSQL 이면 pg_dump -Fc, SQLite 면 파일 사본을 만들고 첨부파일을 압축합니다.
    백업 실행 사실은 감사 로그에도 기록됩니다(앱이 실행 중일 때).

.PARAMETER KeepDays
    보존 기간(일). 기본 30일. 이보다 오래된 백업은 삭제합니다.

.PARAMETER Destination
    추가 보관 위치(네트워크 드라이브 등). 지정 시 사본을 한 벌 더 복사합니다.

.EXAMPLE
    .\backup.ps1 -KeepDays 60 -Destination \\nas\soc-backup
#>
[CmdletBinding()]
param(
    [int]$KeepDays = 30,
    [string]$Destination
)

. "$PSScriptRoot\scripts\common.ps1"
Ensure-Dirs
Import-DotEnv | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$base = "soc_handover_$stamp"
$created = @()

Write-Step "백업 시작 ($stamp)"

# ---------------------------------------------------------------- DB
if (Test-IsPostgres) {
    $pgBin = Resolve-PgBin
    if (-not $pgBin) { Write-Err 'pg_dump 를 찾지 못했습니다(.env 의 PG_BIN 으로 지정 가능).'; exit 1 }
    if ((Test-BundledDb) -and -not (Test-DbReady)) {
        Write-Err 'DB 가 응답하지 않습니다. start.cmd 로 켠 뒤 다시 실행하십시오.'; exit 1
    }

    $target = Join-Path $BackupDir "$base.dump"
    Use-PgCredential | Out-Null
    try {
        & (Join-Path $pgBin 'pg_dump.exe') --format=custom --no-owner --file $target
        $dumpCode = $LASTEXITCODE
    } finally { Clear-PgCredential }
    if ($dumpCode -ne 0) { Write-Err 'pg_dump 실패'; exit 1 }
    $created += $target
    Write-Ok "DB 백업: $(Split-Path -Leaf $target) ($([math]::Round((Get-Item $target).Length/1MB,2))MB)"
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    if (-not (Test-Path $dbFile)) { Write-Err "DB 파일이 없습니다: $dbFile"; exit 1 }
    $target = Join-Path $BackupDir "$base.db"

    # WAL 내용까지 포함한 일관된 사본을 만든다
    if (Test-Path $AppPython) {
        & $AppPython -c @"
import sqlite3, sys
src = sqlite3.connect(r'$dbFile')
dst = sqlite3.connect(r'$target')
with dst:
    src.backup(dst)
dst.close(); src.close()
"@
        if ($LASTEXITCODE -ne 0) { Write-Err 'SQLite 백업 실패'; exit 1 }
    } else {
        Copy-Item $dbFile $target
    }
    $created += $target
    Write-Ok "DB 백업: $(Split-Path -Leaf $target) ($([math]::Round((Get-Item $target).Length/1MB,2))MB)"
}

# ---------------------------------------------------------------- 첨부파일
$attDir = Join-Path $DataDir 'attachments'
if ((Test-Path $attDir) -and (Get-ChildItem $attDir -Recurse -File -ErrorAction SilentlyContinue)) {
    $zip = Join-Path $BackupDir "$base`_attachments.zip"
    Compress-Archive -Path (Join-Path $attDir '*') -DestinationPath $zip -Force
    $created += $zip
    Write-Ok "첨부 백업: $(Split-Path -Leaf $zip)"
} else {
    Write-Ok '첨부파일 없음(건너뜀)'
}

# ---------------------------------------------------------------- 추가 보관
if ($Destination) {
    if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
    foreach ($f in $created) { Copy-Item $f -Destination $Destination -Force }
    Write-Ok "추가 보관 위치로 복사: $Destination"
}

# ---------------------------------------------------------------- 보존 정책
$cutoff = (Get-Date).AddDays(-$KeepDays)
$old = Get-ChildItem $BackupDir -Filter 'soc_handover_*' | Where-Object { $_.LastWriteTime -lt $cutoff }
if ($old) {
    $old | Remove-Item -Force
    Write-Ok "$($old.Count)개의 오래된 백업 삭제 (보존 ${KeepDays}일)"
}

# ---------------------------------------------------------------- 감사 기록
Write-SystemAudit 'BACKUP' @{ files = @($created | ForEach-Object { Split-Path -Leaf $_ }) } | Out-Null

# ---------------------------------------------------------------- 감사로그 보관 정리
# 방금 만든 백업에 들어 있으므로 여기서 지워도 잃지 않는다. 보존기간(설정 retention.audit_days)이 지난 것만.
if (Test-Path $AppPython) {
    Push-Location $BackendDir
    try {
        $archiveOut = Invoke-AppPythonCapture @('manage.py', 'archive-audit')
        if ($LASTEXITCODE -eq 0) { Write-Ok ($archiveOut | Select-Object -Last 1) }
        else { Write-Warn2 '감사로그 보관 정리 실패(백업은 정상). logs\app.log 확인' }
    } finally { Pop-Location }
}

Write-Host ''
Write-Ok "백업 완료 → $BackupDir"
