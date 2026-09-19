<#
.SYNOPSIS
    SOC 인수인계 플랫폼 기동

.DESCRIPTION
    두 가지 방식을 모두 다룹니다.
    · 서비스 모드(설치 프로그램이 관리자 권한으로 설치한 경우): 예약 작업 'SOC-Handover' 를 시작합니다.
      부팅할 때 자동으로 뜨므로 평소에는 실행할 필요가 없습니다. 관리자 권한이 필요합니다(start.cmd 가 요청).
    · 수동 모드: 함께 설치한 DB 를 먼저 띄우고, 앱을 백그라운드로 띄웁니다. 로그오프하면 함께 꺼집니다.

.PARAMETER Foreground
    콘솔에 로그를 출력하며 포그라운드로 실행합니다(Ctrl+C 로 종료). 문제 확인용.

.PARAMETER Dev
    개발 모드(자동 리로드). 프론트엔드는 별도로 npm run dev 를 실행하십시오.
#>
[CmdletBinding()]
param(
    [switch]$Foreground,
    [switch]$Dev
)

. "$PSScriptRoot\scripts\common.ps1"

Ensure-Dirs
Import-DotEnv | Out-Null

if (-not (Test-Path $AppPython)) {
    Write-Err '설치가 완료되지 않았습니다. 설치 프로그램(INSTALL.cmd) 또는 .\install.ps1 을 먼저 실행하십시오.'
    exit 1
}

$appHost = Get-AppHost
$port = Get-AppPort
$displayHost = if ($appHost -eq '0.0.0.0') { [System.Net.Dns]::GetHostName() } else { $appHost }

function Show-Started($Health, [string]$Mode) {
    Write-Ok "기동 완료 ($Mode)"
    Write-Host ''
    Write-Host "  접속 주소 : http://$($displayHost):$port/"
    Write-Host "  DB        : $($Health.database)"
    Write-Host "  로그      : $LogDir"
    Write-Host ''
    if ($Health.database -eq 'sqlite') {
        Write-Warn2 '개발/평가용 SQLite 로 동작 중입니다(운영 비권장).'
    }
}

# ---------------------------------------------------------------- 서비스 모드
if ((Test-ServiceMode) -and -not $Foreground -and -not $Dev) {
    $health = Test-AppHealth 2
    if ($health) {
        Write-Ok '이미 실행 중입니다(서비스 모드).'
        Write-Host "  접속 주소 : http://$($displayHost):$port/"
        exit 0
    }
    if (-not (Test-IsAdmin)) {
        Write-Err '서비스 모드로 설치되어 있어 관리자 권한이 필요합니다. start.cmd 로 실행하십시오.'
        exit 1
    }
    $task = Get-AppTask
    if (-not $task) {
        Write-Err "예약 작업 '$AppTaskName' 이 없습니다. 설치 프로그램(INSTALL.cmd)을 다시 실행하면 복구됩니다."
        exit 1
    }
    Write-Step '서비스 시작'
    if (-not (Start-BundledDb)) { exit 1 }
    Remove-Item $StopFlag -ErrorAction SilentlyContinue
    if ($task.State -eq 'Running') {
        # 실행기는 살아 있는데 앱이 응답하지 않는다 — 실행기가 다시 띄우는 중일 수 있다
        Write-Warn2 '실행기가 앱을 다시 띄우는 중입니다. 잠시 기다립니다.'
    } else {
        Start-ScheduledTask -TaskName $AppTaskName
    }
    $health = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        $health = Test-AppHealth 2
        if ($health) { break }
    }
    if (-not $health) {
        Write-Err '60초 안에 응답이 없습니다. 기록을 확인하십시오:'
        Write-Host "    $(Join-Path $LogDir 'service.log')"
        Write-Host "    $(Join-Path $LogDir 'uvicorn.err.log')"
        exit 1
    }
    Show-Started $health '서비스 모드 — 부팅 시 자동 시작'
    exit 0
}

# ---------------------------------------------------------------- 수동 모드
$existing = Get-AppProcess
if ($existing) {
    Write-Warn2 "이미 실행 중입니다 (PID $($existing.Id)). 중지하려면 .\stop.ps1"
    Write-Host "  접속 주소 : http://$($displayHost):$port/"
    exit 0
}

if (Test-BundledDb) {
    Write-Step 'DB 시작'
    if (-not (Start-BundledDb)) { exit 1 }
    Write-Ok "DB 준비됨 (포트 $(Get-PgPort))"
}

$inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    Write-Err "포트 $port 가 이미 사용 중입니다. .env 의 APP_PORT 를 변경하거나 해당 프로세스를 종료하십시오."
    exit 1
}

$distIndex = Join-Path $FrontendDir 'dist\index.html'
if (-not (Test-Path $distIndex) -and -not $Dev) {
    Write-Warn2 '프론트엔드 빌드 결과가 없습니다. API 만 제공됩니다. (.\install.ps1 로 빌드)'
}

$uvicornArgs = Get-UvicornArgs
if ($Dev) { $uvicornArgs += @('--reload') }

Write-Step '기동 중'

if ($Foreground) {
    Push-Location $BackendDir
    try { & $AppPython @uvicornArgs } finally { Pop-Location }
    exit $LASTEXITCODE
}

$stdout = Join-Path $LogDir 'uvicorn.out.log'
$stderr = Join-Path $LogDir 'uvicorn.err.log'
$proc = Start-Process -FilePath $AppPython -ArgumentList $uvicornArgs `
    -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

$health = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) { break }
    $health = Test-AppHealth 2
    if ($health) { break }
}

if (-not $health) {
    Write-Err '기동에 실패했습니다. 로그를 확인하십시오:'
    Write-Host "    $stderr"
    if (Test-Path $stderr) { Get-Content $stderr -Encoding UTF8 -Tail 20 | ForEach-Object { Write-Host "    $_" } }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 1
}

Show-Started $health "수동 모드, PID $($proc.Id) — 로그오프하거나 PC 를 끄면 멈춥니다"
