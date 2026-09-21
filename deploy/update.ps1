<#
.SYNOPSIS
    SOC 인수인계 플랫폼 — 패치(앱만 교체)

.DESCRIPTION
    이미 설치된 PC 에서 **앱과 화면만** 새 것으로 바꿉니다. Python · PostgreSQL · 데이터는
    그대로 두므로 파일이 작고(수 MB) 금방 끝납니다.

    하는 일
      1. 설치 폴더를 찾고, 패치 파일이 온전한지 검사(MANIFEST.sha256)
      2. 라이브러리 목록(requirements.lock)이 그대로인지 확인 — 바뀌었으면 전체 패키지로 안내하고 멈춤
      3. 앱 중지 → DB 백업 → 지금 파일을 rollback 폴더에 보관
      4. 앱 · 화면 · 스크립트 · 문서 교체 → 마이그레이션 → 앱 시작 → 응답 확인
      5. 중간에 실패하면 보관해 둔 파일로 **되돌리고** 다시 띄웁니다

    DB 는 끄지 않습니다(앱만 바꾸므로). 데이터 · 설정(.env) · 첨부 · 백업은 건드리지 않습니다.

.PARAMETER InstallDir
    설치 폴더. 비우면 예약 작업 · 기본 경로에서 찾습니다.

.PARAMETER Yes
    확인 질문을 생략합니다.

.PARAMETER KeepRollback
    보관할 이전 버전 개수. 기본 3.

.EXAMPLE
    UPDATE.cmd
    UPDATE.cmd -InstallDir D:\SOC-Handover
#>
[CmdletBinding()]
param(
    [string]$InstallDir = '',
    [switch]$Yes,
    [int]$KeepRollback = 3
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Remove-Item env:PYTHONHOME, env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'

$BundleRoot = Split-Path -Parent $PSScriptRoot
$Patch = Join-Path $BundleRoot 'patch'
$Version = (Get-Content (Join-Path $BundleRoot 'VERSION.txt') -TotalCount 1 -ErrorAction SilentlyContinue)
if (-not $Version) { $Version = '?' }
$AppTask = 'SOC-Handover'

$transcript = Join-Path ([IO.Path]::GetTempPath()) ("soc-handover-update-{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
try { Start-Transcript -Path $transcript -Force | Out-Null } catch { }

function Step([string]$m) { Write-Host "`n▶ $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "  ✔ $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail([string]$m) { throw $m }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Quiet([string]$Exe, [string[]]$ArgList, [string]$LogName) {
    # 자식이 표준출력 핸들을 물고 있어도 멈추지 않도록 출력은 파일로 받는다
    $logDir = Join-Path $script:Target 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $out = Join-Path $logDir "$LogName.out.log"
    $err = Join-Path $logDir "$LogName.err.log"
    try {
        # -Wait 대신 WaitForExit: PS 5.1 의 -Wait 는 자손 프로세스까지 기다린다
        $p = Start-Process -FilePath $Exe -ArgumentList $ArgList -NoNewWindow -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError $err
        $null = $p.Handle
        $p.WaitForExit()
        return @{ Code = $p.ExitCode; Out = $out; Err = $err; Message = '' }
    } catch {
        return @{ Code = -2; Out = $out; Err = $err; Message = $_.Exception.Message }
    }
}

function Start-App {
    if ($script:serviceMode) {
        Remove-Item (Join-Path $script:Target 'run\stop.flag') -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName $AppTask
    } else {
        # 파이프로 받지 않는다(앱이 파이프를 물면 패치가 끝나지 않는다)
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:Target 'start.ps1')
    }
}

function Test-Install([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path 'VERSION.txt')) -and (Test-Path (Join-Path $Path '.env')) `
        -and (Test-Path (Join-Path $Path 'backend\app'))
}

function Find-Install {
    if ($InstallDir) {
        if (-not (Test-Install $InstallDir)) {
            Fail "설치 폴더가 아닙니다: $InstallDir (VERSION.txt · .env · backend\app 이 있어야 합니다)"
        }
        return (Resolve-Path $InstallDir).Path
    }
    $seen = New-Object System.Collections.Generic.List[string]
    # 예약 작업(서비스 모드)에 적힌 경로가 가장 확실하다
    try {
        $task = Get-ScheduledTask -TaskName $AppTask -ErrorAction SilentlyContinue
        foreach ($action in @($task.Actions)) {
            if ($action.Arguments -match '-File\s+"?([A-Za-z]:\\[^"]+?)\\[^\\"]+\.ps1') { $seen.Add($Matches[1]) }
        }
    } catch { }
    $seen.Add('C:\SOC-Handover')
    foreach ($d in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        $seen.Add((Join-Path $d.Root 'SOC-Handover'))
    }
    foreach ($candidate in $seen) {
        if (Test-Install $candidate) { return (Resolve-Path $candidate).Path }
    }
    Fail '설치 폴더를 찾지 못했습니다. UPDATE.cmd -InstallDir C:\SOC-Handover 처럼 직접 지정하십시오.'
}

function Get-Revision([string]$Py) {
    # 지금 위치(backend)에서 읽는다 — 부르는 쪽이 Push-Location 한다
    $r = Invoke-Quiet $Py @('-m', 'alembic', 'current') 'patch-revision'
    if ($r.Code -ne 0) { return '?' }
    $text = (Get-Content $r.Out -Encoding UTF8 -ErrorAction SilentlyContinue) -join ' '
    if ($text -match '([0-9a-f]{12})') { return $Matches[1] }
    return '(없음)'
}

function Copy-Tree([string]$From, [string]$To, [switch]$Mirror) {
    $flags = @('/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2')
    if ($Mirror) { $flags = @('/MIR') + $flags } else { $flags = @('/E') + $flags }
    $null = & robocopy.exe $From $To @flags
    if ($LASTEXITCODE -ge 8) { $global:LASTEXITCODE = 0; Fail "파일 복사 실패: $From → $To" }
    $global:LASTEXITCODE = 0
}

#: 교체 대상. 데이터 · 설정 · 런타임(python · pgsql)은 여기 없다 — 패치가 건드리지 않는다.
$Trees = @('backend', 'frontend', 'scripts', 'docs')
$RootFiles = @('*.ps1', '*.cmd', '*.txt', '*.md')

$exitCode = 0
$rollbackDir = $null
$replaced = $false
$migrated = $false
$backupNote = ''

try {
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor White
    Write-Host " SOC 인수인계 플랫폼 — 패치 $Version" -ForegroundColor White
    Write-Host '=====================================================' -ForegroundColor White

    # ============================================================ 1. 대상 확인
    Step '설치 폴더 확인'
    if (-not (Test-Path $Patch)) { Fail 'patch 폴더가 없습니다. 패치 zip 의 압축을 푼 폴더에서 UPDATE.cmd 를 실행하십시오.' }
    $script:Target = Find-Install
    $oldVersion = (Get-Content (Join-Path $Target 'VERSION.txt') -TotalCount 1)
    Ok "설치 폴더: $Target"
    Ok "버전: $oldVersion → $Version"
    if ($oldVersion -eq $Version) { Warn '같은 버전입니다. 그대로 다시 덮어씁니다(문제 없습니다).' }

    $script:serviceMode = Test-Path (Join-Path $Target 'SERVICE_MODE')
    if ($serviceMode -and -not (Test-Admin)) {
        # 서비스 모드는 예약 작업 · 서비스를 건드려야 해 관리자 권한이 필요하다.
        # 수동 모드는 필요 없으므로, 필요할 때만 한 번 요청한다.
        Ok '서비스 모드로 설치되어 있습니다 — 관리자 권한을 요청합니다(새 창).'
        $again = @("-InstallDir `"$Target`"", "-KeepRollback $KeepRollback")
        if ($Yes) { $again += '-Yes' }
        Start-Process -FilePath (Join-Path $BundleRoot 'UPDATE.cmd') -ArgumentList ($again -join ' ') -Verb RunAs
        return
    }
    Ok $(if ($serviceMode) { '설치 방식: 서비스 모드' } else { '설치 방식: 수동 모드' })

    $py = Join-Path $Target 'runtime\python\python.exe'
    if (-not (Test-Path $py)) { Fail "설치된 Python 을 찾지 못했습니다: $py" }

    # ============================================================ 2. 패치 파일 검사
    Step '패치 파일 검사'
    $manifest = Join-Path $BundleRoot 'MANIFEST.sha256'
    if (-not (Test-Path $manifest)) { Fail 'MANIFEST.sha256 이 없습니다. 패치 파일을 다시 받으십시오.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    $bad = New-Object System.Collections.Generic.List[string]
    $n = 0
    foreach ($line in (Get-Content $manifest -Encoding UTF8)) {
        if (-not $line) { continue }
        $hash = $line.Substring(0, 64); $rel = $line.Substring(66)
        $path = Join-Path $BundleRoot $rel
        if (-not (Test-Path -LiteralPath $path)) { $bad.Add("없음: $rel"); continue }
        $fs = [IO.File]::OpenRead($path)
        try { $h = -join ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString('x2') }) } finally { $fs.Dispose() }
        if ($h -ne $hash) { $bad.Add("손상: $rel") }
        $n++
    }
    if ($bad.Count) {
        $bad | Select-Object -First 10 | ForEach-Object { Warn $_ }
        Fail "패치 파일 $($bad.Count)개가 없거나 손상되었습니다. zip 을 다시 복사해 압축을 푸십시오."
    }
    Ok "$n 개 파일 이상 없음"
    Get-ChildItem -LiteralPath $BundleRoot -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

    # 라이브러리가 바뀌었으면 앱만 바꿔서는 돌지 않는다 — 전체 패키지로 안내하고 멈춘다.
    $newLock = Join-Path $Patch 'backend\requirements.lock'
    $oldLock = Join-Path $Target 'backend\requirements.lock'
    if ((Test-Path $newLock) -and (Test-Path $oldLock)) {
        $a = (Get-FileHash $newLock -Algorithm SHA256).Hash
        $b = (Get-FileHash $oldLock -Algorithm SHA256).Hash
        if ($a -ne $b) {
            Fail ('이 패치는 Python 라이브러리가 바뀌었습니다. 앱만 바꾸면 실행되지 않습니다. ' +
                  '전체 설치 패키지(SOC-Handover-<버전>-offline.zip)로 업그레이드하십시오. 데이터는 그대로 유지됩니다.')
        }
    }
    Ok '라이브러리 그대로 — 앱만 바꾸면 됩니다'

    if (-not $Yes) {
        Write-Host ''
        Write-Host '  앱 · 화면만 바꿉니다. 데이터 · 설정 · 첨부 · 백업은 그대로입니다.'
        Write-Host '  바꾸기 전에 DB 를 백업하고, 지금 파일도 되돌릴 수 있게 보관합니다.'
        $answer = Read-Host '패치할까요? (Y/N)'
        if ($answer -notmatch '^[Yy]') { Write-Host '취소했습니다.'; $exitCode = 2; return }
    }

    # ============================================================ 3. 중지 · 백업 · 보관
    Step '앱 중지 · 백업'
    # 주의: 앱 · DB 를 띄울 수 있는 자식의 출력을 파이프로 받지 않는다(파이프를 물고 있어 멈춘다)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Target 'stop.ps1') -KeepDb
    Ok '앱 중지 (DB 는 켜 둡니다 — 백업 · 마이그레이션에 필요)'

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
        ". '$Target\scripts\common.ps1'; Import-DotEnv | Out-Null; if (-not (Start-BundledDb)) { exit 1 }"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Target 'backup.ps1') -KeepDays 3650
    if ($LASTEXITCODE -ne 0) { Fail '패치 전 백업에 실패했습니다. 패치를 멈춥니다(지금 설치는 그대로입니다).' }
    $lastBackup = Get-ChildItem (Join-Path $Target 'backup') -Filter *.dump -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($lastBackup) { $backupNote = $lastBackup.FullName }
    Ok "백업 완료$(if ($backupNote) { ": $backupNote" })"

    $rollbackRoot = Join-Path $Target 'rollback'
    $rollbackDir = Join-Path $rollbackRoot ("{0}_{1}" -f $oldVersion, (Get-Date -Format 'yyyyMMdd_HHmmss'))
    New-Item -ItemType Directory -Path $rollbackDir -Force | Out-Null
    foreach ($d in $Trees) {
        $src = Join-Path $Target $d
        if (Test-Path $src) { Copy-Tree $src (Join-Path $rollbackDir $d) }
    }
    foreach ($pattern in $RootFiles) {
        Get-ChildItem -LiteralPath $Target -Filter $pattern -File -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName $rollbackDir -Force }
    }
    Ok "지금 파일 보관: $rollbackDir"

    # ============================================================ 4. 교체
    Step '앱 · 화면 교체'
    Push-Location (Join-Path $Target 'backend')
    try { $revBefore = Get-Revision $py } finally { Pop-Location }

    foreach ($d in $Trees) {
        $src = Join-Path $Patch $d
        if (-not (Test-Path $src)) { continue }
        # /MIR: 이전 버전에만 있던 파일은 지운다(데이터 · 설정 폴더는 대상이 아니다)
        Copy-Tree $src (Join-Path $Target $d) -Mirror
    }
    $null = & robocopy.exe $Patch $Target @RootFiles /NFL /NDL /NJH /NJS /NP /R:2 /W:2
    if ($LASTEXITCODE -ge 8) { $global:LASTEXITCODE = 0; Fail '파일 복사 실패' }
    $global:LASTEXITCODE = 0
    $replaced = $true
    Ok '교체 완료'

    # ============================================================ 5. 마이그레이션
    Step '데이터베이스 구조 (마이그레이션)'
    Push-Location (Join-Path $Target 'backend')
    try {
        # alembic 은 진행 기록을 표준오류로 쓴다 — PS 5.1 에서 2>&1 로 받으면 오류로 멈추므로 파일로 받는다
        $r = Invoke-Quiet $py @('-m', 'alembic', 'upgrade', 'head') 'patch-migrate'
        Get-Content $r.Err -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'Running upgrade' } |
            ForEach-Object { Write-Host "    $($_ -replace '^.*Running upgrade ', '')" }
        if ($r.Code -ne 0) {
            Get-Content $r.Err -Encoding UTF8 -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Warn $_ }
            $revAfter = Get-Revision $py
            $script:migrated = ($revAfter -ne $revBefore)
            Fail "마이그레이션 실패. 로그: $($r.Err)"
        }
        $migrated = $true
        Ok '최신 구조 적용'
        $r = Invoke-Quiet $py @('manage.py', 'bootstrap') 'patch-bootstrap'
        if ($r.Code -ne 0) {
            Get-Content $r.Err -Encoding UTF8 -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Warn $_ }
            Fail '기준 데이터(상태 · 교대 · 설정) 구성 실패'
        }
        Ok '기준 데이터 확인'
    } finally { Pop-Location }

    # ============================================================ 6. 시작 · 확인
    Step '시작'
    $appPort = 8080
    foreach ($line in (Get-Content (Join-Path $Target '.env') -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*APP_PORT\s*=\s*(\d+)') { $appPort = [int]$Matches[1] }
    }
    Start-App
    $health = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$appPort/api/v1/health" -TimeoutSec 2 } catch { }
        if ($health -and $health.database_ok) { break }
    }
    if (-not ($health -and $health.database_ok)) {
        Fail "앱이 60초 안에 응답하지 않습니다. 로그: $Target\logs (service.log, uvicorn.err.log)"
    }
    Ok "응답 확인: 버전 $($health.version), DB $($health.database)"

    Copy-Item (Join-Path $BundleRoot 'VERSION.txt') (Join-Path $Target 'VERSION.txt') -Force

    # 오래된 보관본 정리
    $old = Get-ChildItem (Join-Path $Target 'rollback') -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -Skip $KeepRollback
    foreach ($dir in $old) { Remove-Item $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host ' 패치 완료' -ForegroundColor Green
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host "  버전     : $oldVersion → $Version"
    Write-Host "  접속     : http://localhost:$appPort/"
    Write-Host "  되돌리기 : $rollbackDir (파일) / $backupNote (DB)"
    Write-Host ''
} catch {
    $exitCode = 1
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Red
    Write-Host ' 패치 실패' -ForegroundColor Red
    Write-Host '=====================================================' -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red

    if ($replaced -and $rollbackDir -and (Test-Path $rollbackDir)) {
        Write-Host ''
        Step '되돌리는 중'
        try {
            foreach ($d in $Trees) {
                $src = Join-Path $rollbackDir $d
                if (Test-Path $src) { Copy-Tree $src (Join-Path $script:Target $d) -Mirror }
            }
            $null = & robocopy.exe $rollbackDir $script:Target @RootFiles /NFL /NDL /NJH /NJS /NP /R:2 /W:2
            $global:LASTEXITCODE = 0
            Ok "이전 버전($oldVersion) 파일로 되돌렸습니다"
            Start-App
            Ok '앱을 다시 띄웠습니다'
        } catch {
            Warn "되돌리기에 실패했습니다: $($_.Exception.Message)"
            Warn "직접 되돌리려면 $rollbackDir 의 내용을 $script:Target 에 덮어쓰십시오."
        }
        if ($migrated) {
            Write-Host ''
            Warn 'DB 구조가 이미 바뀌었습니다 — 이전 버전 앱과 맞지 않을 수 있습니다.'
            Warn "그런 경우 restore.cmd 로 방금 만든 백업을 되돌리십시오: $backupNote"
        }
    } else {
        Write-Host '  파일을 아직 바꾸지 않았습니다 — 지금 설치는 그대로입니다.' -ForegroundColor Yellow
    }
    Write-Host ''
} finally {
    try { Stop-Transcript | Out-Null } catch { }
    Write-Host "기록: $transcript"
}
exit $exitCode
