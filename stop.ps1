<#
.SYNOPSIS
    SOC 인수인계 플랫폼 중지

.DESCRIPTION
    · 서비스 모드: 실행기에 중지를 알리고(다시 띄우지 않게) 앱을 끕니다. DB 서비스는 그대로 둡니다
      (-IncludeDb 로 함께 끌 수 있음). 관리자 권한이 필요합니다(stop.cmd 가 요청).
      다음 부팅 때는 다시 자동으로 켜집니다.
    · 수동 모드: 앱을 끄고, 함께 설치한 DB 도 끕니다(-KeepDb 로 DB 는 유지).

.PARAMETER Force
    정상 종료를 기다리지 않고 즉시 종료합니다.

.PARAMETER IncludeDb
    서비스 모드에서 DB 서비스까지 멈춥니다(복구 · 점검용).

.PARAMETER KeepDb
    수동 모드에서 DB 는 켜 둡니다.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$IncludeDb,
    [switch]$KeepDb
)

. "$PSScriptRoot\scripts\common.ps1"
Ensure-Dirs
Import-DotEnv | Out-Null

$serviceMode = Test-ServiceMode
$task = $null
if ($serviceMode) {
    if (-not (Test-IsAdmin)) {
        Write-Err '서비스 모드로 설치되어 있어 관리자 권한이 필요합니다. stop.cmd 로 실행하십시오.'
        exit 1
    }
    $task = Get-AppTask
    # 실행기가 앱을 다시 띄우지 않게 먼저 알린다
    Set-Content -Path $StopFlag -Value (Get-Date -Format s) -Encoding ASCII
}

$proc = Get-AppProcess

if (-not $proc) {
    # PID 파일이 없거나 죽은 경우 포트로 역추적
    $port = Get-AppPort
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $owner = Get-Process -Id @($conn)[0].OwningProcess -ErrorAction SilentlyContinue
        if (Test-IsAppPython $owner) {
            $proc = $owner
            Write-Warn2 "PID 파일이 없어 포트 $port 점유 프로세스를 대상으로 합니다."
        } elseif ($owner) {
            Write-Warn2 "포트 $port 를 이 앱이 아닌 프로세스($($owner.ProcessName), PID $($owner.Id))가 쓰고 있습니다. 건드리지 않습니다."
        }
    }
}

if ($proc) {
    Write-Step "앱 중지 (PID $($proc.Id))"
    try {
        # 일부 Python 배포판에서는 런처가 실제 서버를 자식 프로세스로 띄운다.
        # 부모만 종료하면 포트가 계속 물려 있으므로 자식까지 함께 정리한다.
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.Id)" `
                        -ErrorAction SilentlyContinue

        Stop-Process -Id $proc.Id -Force:$Force -ErrorAction Stop
        foreach ($c in $children) {
            Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue
        }

        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 300
            if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
        }
        if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }

        # 포트가 여전히 점유되어 있으면 남은 프로세스를 정리한다.
        $port = Get-AppPort
        for ($i = 0; $i -lt 10; $i++) {
            $left = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if (-not $left) { break }
            foreach ($l in @($left)) {
                $owner = Get-Process -Id $l.OwningProcess -ErrorAction SilentlyContinue
                if (Test-IsAppPython $owner) { Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue }
            }
            Start-Sleep -Milliseconds 400
        }

        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            Write-Warn2 "포트 $port 가 아직 점유되어 있습니다. 수동 확인이 필요합니다."
        } else {
            Write-Ok '앱 중지 완료'
        }
    } catch {
        Write-Err "중지 실패: $($_.Exception.Message)"
        exit 1
    } finally {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }
} else {
    Write-Ok '실행 중인 앱이 없습니다.'
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

# 서비스 모드: 실행기가 중지 표시를 보고 스스로 끝난다. 남아 있으면 작업을 멈춘다.
if ($task) {
    for ($i = 0; $i -lt 10; $i++) {
        if ((Get-ScheduledTask -TaskName $AppTaskName).State -ne 'Running') { break }
        Start-Sleep -Milliseconds 500
    }
    if ((Get-ScheduledTask -TaskName $AppTaskName).State -eq 'Running') {
        Stop-ScheduledTask -TaskName $AppTaskName
    }
    Write-Ok '서비스 실행기 중지 (다음 부팅 때 다시 자동 시작)'
}

# ---------------------------------------------------------------- DB
if (Test-BundledDb) {
    $stopDb = if ($serviceMode) { [bool]$IncludeDb } else { -not $KeepDb }
    if ($stopDb) {
        Write-Step 'DB 중지'
        if (Stop-BundledDb) { Write-Ok 'DB 중지 완료' }
        else { Write-Warn2 "DB 를 멈추지 못했습니다. 로그: $(Join-Path $LogDir 'pg_ctl')" }
    }
}
