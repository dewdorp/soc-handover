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
Write-Host "  현재 DB   : $((Get-EnvValue 'DATABASE_URL') -replace '://([^:/@]+):[^@]*@', '://$1:***@')"
Write-Host '───────────────────────────────────────────────' -ForegroundColor Yellow

if (-not $Yes) {
    $answer = Read-Host '계속하려면 RESTORE 를 입력하십시오'
    if ($answer -ne 'RESTORE') { Write-Host '취소되었습니다.'; exit 0 }
}

if ((Test-IsPostgres) -and $File -like '*.db') {
    Write-Err '이 설치본은 PostgreSQL 을 씁니다. SQLite 백업(.db)은 복구할 수 없습니다(Excel 내보내기/가져오기로 옮기십시오).'
    exit 1
}
if ((Test-ServiceMode) -and -not (Test-IsAdmin)) {
    Write-Err '서비스 모드로 설치되어 있어 관리자 권한이 필요합니다. restore.cmd 로 실행하십시오.'
    exit 1
}

# ---------------------------------------------------------------- 서비스 중지
$wasRunning = [bool](Get-AppProcess) -or [bool](Test-AppHealth 2)
if ($wasRunning) {
    Write-Step '앱 중지 (DB 는 켜 둠)'
    & "$PSScriptRoot\stop.ps1" -KeepDb | Out-Null
}
if ((Test-BundledDb) -and -not (Start-BundledDb)) { exit 1 }

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
    $pgBin = Resolve-PgBin
    if (-not $pgBin) { Write-Err 'pg_restore 를 찾지 못했습니다(.env 의 PG_BIN 으로 지정 가능).'; exit 1 }
    $psql = Join-Path $pgBin 'psql.exe'
    $pgRestore = Join-Path $pgBin 'pg_restore.exe'

    if ((Test-BundledDb) -and (Get-EnvValue 'PG_SUPERUSER_PASSWORD')) {
        # 함께 설치한 DB: 데이터베이스를 지우고 새로 만든 뒤 그대로 되살린다(남는 객체 없이 깨끗하게)
        $info = Use-PgCredential -Superuser
        $restoreCode = 0
        try {
            $db = $info.Db; $owner = $info.User
            & $psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();" | Out-Null
            & $psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS `"$db`";"
            if ($LASTEXITCODE -ne 0) { throw 'DROP DATABASE 실패' }
            & $psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE `"$db`" OWNER `"$owner`" ENCODING 'UTF8' TEMPLATE template0;"
            if ($LASTEXITCODE -ne 0) { throw 'CREATE DATABASE 실패' }
            # 객체 주인은 앱 계정으로(--role), 확장 주석처럼 앱 계정이 못 바꾸는 것은 건너뛴다
            & $pgRestore --no-owner "--role=$owner" --no-comments --exit-on-error --dbname $db $File
            $restoreCode = $LASTEXITCODE
        } catch {
            Write-Err "복구 준비 실패: $($_.Exception.Message)"
            $restoreCode = 1
        } finally { Clear-PgCredential }
    } else {
        # 따로 운영하는 PostgreSQL: 앱 계정으로 기존 객체를 지우고 덮어쓴다
        Use-PgCredential | Out-Null
        try {
            & $pgRestore --clean --if-exists --no-owner --dbname $env:PGDATABASE $File
            $restoreCode = $LASTEXITCODE
        } finally { Clear-PgCredential }
    }
    if ($restoreCode -ne 0) {
        Write-Err 'pg_restore 실패. 복구 직전 상태는 방금 만든 안전 백업으로 되돌릴 수 있습니다(backup 폴더의 최신 .dump).'
        exit 1
    }
} else {
    $dbFile = Join-Path $DataDir 'soc_handover.db'
    foreach ($sfx in @('', '-wal', '-shm')) {
        $p = "$dbFile$sfx"
        if (Test-Path $p) { Remove-Item $p -Force }
    }
    Copy-Item $File $dbFile -Force
}
Write-Ok 'DB 복구 완료'

# 같은 시각에 만든 첨부 백업이 있으면 함께 되살린다. 첨부는 무작위 이름이라 덮어써도 다른 파일을 해치지 않는다.
$attZip = Join-Path (Split-Path -Parent $File) ("{0}_attachments.zip" -f [IO.Path]::GetFileNameWithoutExtension($File))
if (Test-Path $attZip) {
    Write-Step '첨부 파일 복구'
    Expand-Archive -Path $attZip -DestinationPath (Join-Path $DataDir 'attachments') -Force
    Write-Ok "첨부 복구: $(Split-Path -Leaf $attZip)"
}

# ---------------------------------------------------------------- 스키마 최신화
Write-Step '스키마 확인'
Push-Location $BackendDir
try {
    & $AppPython -m alembic upgrade head
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
