<#
.SYNOPSIS
    서비스 모드 실행기 — 작업 스케줄러가 부팅 때 SYSTEM 권한으로 실행한다(설치 프로그램이 등록).

.DESCRIPTION
    1) 함께 설치한 DB 가 준비될 때까지 기다린다(부팅 직후 DB 서비스가 늦게 뜰 수 있다).
    2) 앱(uvicorn)을 띄우고 끝날 때까지 기다린다.
    3) 앱이 죽으면 다시 띄운다. 곧바로 계속 죽으면 간격을 늘린다(최대 60초).
    4) stop.ps1 이 run\stop.flag 를 만들면 다시 띄우지 않고 끝낸다.

    직접 실행하지 않는다. 시작 · 중지는 start.ps1 / stop.ps1 (또는 start.cmd / stop.cmd).
    기록은 logs\service.log 에 남는다.
#>
[CmdletBinding()]
param()

. "$PSScriptRoot\common.ps1"
# 실행기 자체는 오류로 멈추지 않고 기록한 뒤 다시 시도한다
$ErrorActionPreference = 'Continue'

Ensure-Dirs
Import-DotEnv | Out-Null
# 파일 로그(app.log · error.log)는 회전되지만 표준오류 파일은 회전되지 않는다 — 콘솔 로그를 끈다
$env:LOG_CONSOLE = 'false'

$serviceLog = Join-Path $LogDir 'service.log'
function Write-ServiceLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    try { Add-Content -Path $serviceLog -Value $line -Encoding UTF8 } catch { }
}

# service.log 도 너무 커지지 않게(5MB 넘으면 한 벌만 남기고 새로 시작)
if ((Test-Path $serviceLog) -and (Get-Item $serviceLog).Length -gt 5MB) {
    Move-Item $serviceLog "$serviceLog.1" -Force -ErrorAction SilentlyContinue
}

Remove-Item $StopFlag -ErrorAction SilentlyContinue
Write-ServiceLog "실행기 시작 (PID $PID, 사용자 $env:USERNAME)"

# ---------------------------------------------------------------- DB 준비 대기
if (Test-BundledDb) {
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        if (Test-Path $StopFlag) { Write-ServiceLog '중지 요청 — DB 대기 중 종료'; exit 0 }
        if (Test-DbReady) { $ready = $true; break }
        $svc = Get-DbService
        if ($svc -and $svc.Status -eq 'Stopped' -and ($i % 15) -eq 0) {
            Write-ServiceLog "DB 서비스가 멈춰 있어 시작합니다: $($svc.Name)"
            Start-Service -Name $svc.Name -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }
    if ($ready) { Write-ServiceLog 'DB 준비됨' }
    else { Write-ServiceLog 'DB 가 3분 안에 준비되지 않았습니다 — 앱은 띄우고 DB 를 계속 기다립니다(health 가 degraded)' }
}

# ---------------------------------------------------------------- 앱 실행 · 감시
$stdout = Join-Path $LogDir 'uvicorn.out.log'
$stderr = Join-Path $LogDir 'uvicorn.err.log'
$fails = 0

while (-not (Test-Path $StopFlag)) {
    # 직전 실행의 표준오류는 한 벌 남긴다(바로 죽은 원인을 볼 수 있게)
    if (Test-Path $stderr) { Move-Item $stderr "$stderr.prev" -Force -ErrorAction SilentlyContinue }

    $started = Get-Date
    try {
        $proc = Start-Process -FilePath $AppPython -ArgumentList (Get-UvicornArgs) `
            -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    } catch {
        Write-ServiceLog "앱을 띄우지 못했습니다: $($_.Exception.Message)"
        Start-Sleep -Seconds 30
        continue
    }
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
    Write-ServiceLog "앱 시작 (PID $($proc.Id), 포트 $(Get-AppPort))"

    $proc.WaitForExit()
    $code = $proc.ExitCode
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    if (Test-Path $StopFlag) { Write-ServiceLog "앱 종료 (중지 요청, 코드 $code)"; break }

    $ranFor = [int]((Get-Date) - $started).TotalSeconds
    Write-ServiceLog "앱이 예기치 않게 종료되었습니다 (코드 $code, ${ranFor}초 실행) — 다시 띄웁니다. 원인: $stderr.prev"
    if ($ranFor -lt 60) { $fails++ } else { $fails = 0 }
    $wait = [math]::Min(60, 5 * [math]::Pow(2, [math]::Min($fails, 4)))
    for ($i = 0; $i -lt $wait; $i++) {
        if (Test-Path $StopFlag) { break }
        Start-Sleep -Seconds 1
    }
}

Write-ServiceLog '실행기 종료'
exit 0
