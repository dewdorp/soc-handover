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
    $pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
    if (-not $pgDump) {
        foreach ($p in @('C:\Program Files\PostgreSQL\17\bin', 'C:\Program Files\PostgreSQL\16\bin',
                         'C:\Program Files\PostgreSQL\15\bin')) {
            if (Test-Path (Join-Path $p 'pg_dump.exe')) { $pgDump = Join-Path $p 'pg_dump.exe'; break }
        }
    } else { $pgDump = $pgDump.Source }

    if (-not $pgDump) { Write-Err 'pg_dump 를 찾지 못했습니다.'; exit 1 }

    # DATABASE_URL(postgresql+psycopg://user:pw@host:port/db) → libpq URL 로 변환
    $url = Get-EnvValue 'DATABASE_URL'
    $libpq = $url -replace '^postgresql\+\w+://', 'postgresql://'
    $target = Join-Path $BackupDir "$base.dump"

    & $pgDump --format=custom --no-owner --file $target $libpq
    if ($LASTEXITCODE -ne 0) { Write-Err 'pg_dump 실패'; exit 1 }
    $created += $target
    Write-Ok "DB 백업: $(Split-Path -Leaf $target) ($([math]::Round((Get-Item $target).Length/1MB,2))MB)"
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    if (-not (Test-Path $dbFile)) { Write-Err "DB 파일이 없습니다: $dbFile"; exit 1 }
    $target = Join-Path $BackupDir "$base.db"

    # WAL 내용까지 포함한 일관된 사본을 만든다
    if (Test-Path $VenvPython) {
        & $VenvPython -c @"
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

Write-Host ''
Write-Ok "백업 완료 → $BackupDir"
