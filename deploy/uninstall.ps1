<#
.SYNOPSIS
    SOC 인수인계 플랫폼 제거

.DESCRIPTION
    자동 시작 · 백업 예약 작업, DB 서비스, 방화벽 규칙, 바탕화면 바로가기, 프로그램 파일을 지웁니다.
    기본으로 **데이터는 남깁니다**(data · backup · logs · .env). 같은 폴더에 다시 설치하면 그대로 이어서 씁니다.

.PARAMETER RemoveData
    데이터(DB · 첨부 · 백업 · 설정)까지 모두 지웁니다. 되돌릴 수 없습니다 — 확인 문구를 입력해야 진행합니다.
    지우기 전에 backup 폴더를 다른 곳에 복사해 두십시오.
#>
[CmdletBinding()]
param([switch]$RemoveData)

. "$PSScriptRoot\scripts\common.ps1"
Import-DotEnv | Out-Null

if (((Test-ServiceMode) -or (Get-DbService)) -and -not (Test-IsAdmin)) {
    Write-Err '관리자 권한이 필요합니다. uninstall.cmd 로 실행하십시오.'
    exit 1
}

Write-Host ''
Write-Host '───────────────────────────────────────────────' -ForegroundColor Yellow
Write-Host " SOC 인수인계 플랫폼 제거: $Root" -ForegroundColor Yellow
if ($RemoveData) {
    Write-Host ' 데이터(DB · 첨부 · 백업 · 설정)까지 모두 지웁니다. 되돌릴 수 없습니다.' -ForegroundColor Red
} else {
    Write-Host ' 프로그램만 지우고 데이터(data · backup · logs · .env)는 남깁니다.' -ForegroundColor Yellow
}
Write-Host '───────────────────────────────────────────────' -ForegroundColor Yellow
$word = if ($RemoveData) { 'DELETE-ALL' } else { 'UNINSTALL' }
$answer = Read-Host "계속하려면 $word 를 입력하십시오"
if ($answer -ne $word) { Write-Host '취소했습니다.'; exit 0 }

Write-Step '중지'
& "$PSScriptRoot\stop.ps1" -IncludeDb

Write-Step '자동 시작 · 백업 · 방화벽 · 서비스 해제'
foreach ($t in @($AppTaskName, $BackupTaskName)) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Ok "예약 작업 삭제: $t"
    }
}
$rule = Get-NetFirewallRule -Name 'SOC-Handover-App' -ErrorAction SilentlyContinue
if ($rule) { $rule | Remove-NetFirewallRule; Write-Ok '방화벽 규칙 삭제' }

$svc = Get-DbService
if ($svc) {
    if ($svc.Status -ne 'Stopped') { Stop-Service -Name $svc.Name -Force }
    & (Join-Path (Resolve-PgBin) 'pg_ctl.exe') unregister -N $svc.Name
    if ($LASTEXITCODE -eq 0) { Write-Ok "DB 서비스 삭제: $($svc.Name)" }
    else { Write-Warn2 "DB 서비스 삭제 실패 — 'sc.exe delete $($svc.Name)' 로 지우십시오." }
}
foreach ($desk in @([Environment]::GetFolderPath('CommonDesktopDirectory'), [Environment]::GetFolderPath('Desktop'))) {
    if ($desk) { Remove-Item (Join-Path $desk 'SOC 인수인계.url') -ErrorAction SilentlyContinue }
}

Write-Step '파일 삭제'
# 이 스크립트가 쓰는 common.ps1(scripts)은 마지막에 지운다
$programItems = @('backend', 'frontend', 'runtime', 'docs', 'SERVICE_MODE', 'VERSION.txt',
                  'start.ps1', 'stop.ps1', 'status.ps1', 'backup.ps1', 'restore.ps1',
                  'start.cmd', 'stop.cmd', 'status.cmd', 'backup.cmd', 'restore.cmd', 'README-KO.txt')
foreach ($i in $programItems) {
    $p = Join-Path $Root $i
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
if ($RemoveData) {
    foreach ($i in @('data', 'backup', 'logs', 'run', '.env')) {
        $p = Join-Path $Root $i
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Write-Ok '데이터까지 삭제'
} else {
    Write-Ok "프로그램 삭제 — 데이터는 남아 있습니다: $Root\data, $Root\backup"
    Write-Host '    같은 폴더(-InstallDir)에 다시 설치하면 이 데이터로 이어서 시작합니다.'
}

$scripts = Join-Path $Root 'scripts'
$self = $MyInvocation.MyCommand.Path
# 실행 중인 자신(uninstall.ps1 · uninstall.cmd)과 scripts 폴더는 창이 닫힌 뒤 지운다
$cleanup = "Start-Sleep -Seconds 3; Remove-Item -LiteralPath '$scripts' -Recurse -Force -ErrorAction SilentlyContinue; " +
           "Remove-Item -LiteralPath '$self', '$(Join-Path $Root 'uninstall.cmd')' -Force -ErrorAction SilentlyContinue"
if ($RemoveData) { $cleanup += "; Remove-Item -LiteralPath '$Root' -Force -ErrorAction SilentlyContinue" }
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-WindowStyle', 'Hidden', '-Command', $cleanup -WindowStyle Hidden

Write-Host ''
Write-Ok '제거 완료'
