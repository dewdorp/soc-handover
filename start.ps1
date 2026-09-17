<#
.SYNOPSIS
    SOC 인수인계 플랫폼 기동

.PARAMETER Foreground
    콘솔에 로그를 출력하며 포그라운드로 실행합니다(Ctrl+C 로 종료).

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

if (-not (Test-Path $VenvPython)) {
    Write-Err '설치가 완료되지 않았습니다. 먼저 .\install.ps1 을 실행하십시오.'
    exit 1
}

$existing = Get-AppProcess
if ($existing) {
    Write-Warn2 "이미 실행 중입니다 (PID $($existing.Id)). 중지하려면 .\stop.ps1"
    Write-Host "  주소: http://$(Get-AppHost):$(Get-AppPort)/"
    exit 0
}

$appHost = Get-AppHost
$port = Get-AppPort

$inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    Write-Err "포트 $port 가 이미 사용 중입니다. .env 의 APP_PORT 를 변경하거나 해당 프로세스를 종료하십시오."
    exit 1
}

$distIndex = Join-Path $FrontendDir 'dist\index.html'
if (-not (Test-Path $distIndex) -and -not $Dev) {
    Write-Warn2 '프론트엔드 빌드 결과가 없습니다. API 만 제공됩니다. (.\install.ps1 로 빌드)'
}

$uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', $appHost, '--port', "$port")
if ($Dev) { $uvicornArgs += @('--reload') }

$cert = Get-EnvValue 'SSL_CERTFILE'
$key = Get-EnvValue 'SSL_KEYFILE'
if ($cert -and $key -and (Test-Path $cert) -and (Test-Path $key)) {
    $uvicornArgs += @('--ssl-certfile', $cert, '--ssl-keyfile', $key)
    Write-Ok 'HTTPS 사용'
}

Write-Step '기동 중'

if ($Foreground) {
    Push-Location $BackendDir
    try { & $VenvPython @uvicornArgs } finally { Pop-Location }
    exit $LASTEXITCODE
}

$stdout = Join-Path $LogDir 'uvicorn.out.log'
$stderr = Join-Path $LogDir 'uvicorn.err.log'
$proc = Start-Process -FilePath $VenvPython -ArgumentList $uvicornArgs `
    -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

$health = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) { break }
    $health = Test-AppHealth 2
    if ($health) { break }
}

if (-not $health) {
    Write-Err '기동에 실패했습니다. 로그를 확인하십시오:'
    Write-Host "    $stderr"
    if (Test-Path $stderr) { Get-Content $stderr -Tail 20 | ForEach-Object { Write-Host "    $_" } }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 1
}

$displayHost = if ($appHost -eq '0.0.0.0') { [System.Net.Dns]::GetHostName() } else { $appHost }
Write-Ok "기동 완료 (PID $($proc.Id))"
Write-Host ''
Write-Host "  접속 주소 : http://$($displayHost):$port/"
Write-Host "  DB        : $($health.database)"
Write-Host "  로그      : $LogDir"
Write-Host ''
if ($health.database -eq 'sqlite') {
    Write-Warn2 '개발/평가용 SQLite 로 동작 중입니다(운영 비권장).'
}
