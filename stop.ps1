<#
.SYNOPSIS
    SOC 인수인계 플랫폼 중지
.PARAMETER Force
    정상 종료를 기다리지 않고 즉시 종료합니다.
#>
[CmdletBinding()]
param([switch]$Force)

. "$PSScriptRoot\scripts\common.ps1"
Import-DotEnv | Out-Null

$proc = Get-AppProcess

if (-not $proc) {
    # PID 파일이 없거나 죽은 경우 포트로 역추적
    $port = Get-AppPort
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) { Write-Warn2 "PID 파일이 없어 포트 $port 점유 프로세스를 대상으로 합니다." }
    }
}

if (-not $proc) {
    Write-Ok '실행 중인 프로세스가 없습니다.'
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 0
}

Write-Step "중지 중 (PID $($proc.Id))"
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
            Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 400
    }

    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Warn2 "포트 $port 가 아직 점유되어 있습니다. 수동 확인이 필요합니다."
    } else {
        Write-Ok '중지 완료'
    }
} catch {
    Write-Err "중지 실패: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}
