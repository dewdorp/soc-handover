# 공통 유틸. 각 스크립트에서 dot-source 한다.
# Windows PowerShell 5.1 및 PowerShell 7 모두에서 동작한다.

$ErrorActionPreference = 'Stop'

# 한국어 Windows 의 기본 ANSI 코드페이지는 cp949 다. 일부 라이브러리(alembic 등)가
# encoding="locale" 로 설정파일을 읽으므로, Python 을 UTF-8 모드로 고정해 둔다.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$script:Root = Split-Path -Parent $PSScriptRoot
$script:BackendDir = Join-Path $Root 'backend'
$script:FrontendDir = Join-Path $Root 'frontend'
$script:RunDir = Join-Path $Root 'run'
$script:LogDir = Join-Path $Root 'logs'
$script:DataDir = Join-Path $Root 'data'
$script:BackupDir = Join-Path $Root 'backup'
$script:EnvFile = Join-Path $Root '.env'
$script:PidFile = Join-Path $RunDir 'app.pid'
$script:VenvPython = Join-Path $BackendDir '.venv\Scripts\python.exe'

function Write-Step([string]$Message) { Write-Host "`n▶ $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "  ✔ $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message) { Write-Host "  ! $Message" -ForegroundColor Yellow }
function Write-Err([string]$Message) { Write-Host "  ✘ $Message" -ForegroundColor Red }

function Ensure-Dirs {
    foreach ($d in @($RunDir, $LogDir, $DataDir, $BackupDir)) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }
}

# .env 를 읽어 현재 프로세스 환경변수로 설정한다.
function Import-DotEnv([string]$Path = $EnvFile) {
    if (-not (Test-Path $Path)) { return @{} }
    $map = @{}
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $idx = $t.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $t.Substring(0, $idx).Trim()
        $val = $t.Substring($idx + 1).Trim()
        if ($val.StartsWith('"') -and $val.EndsWith('"') -and $val.Length -ge 2) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $map[$key] = $val
        Set-Item -Path "env:$key" -Value $val
    }
    return $map
}

function Get-EnvValue([string]$Key, [string]$Default = '') {
    $v = [Environment]::GetEnvironmentVariable($Key)
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v
}

# 시스템 PATH → 일반 설치 경로 → codex 번들 순으로 Python 을 찾는다(ASSUMPTIONS A-02).
function Resolve-PythonExe {
    if (Test-Path $VenvPython) { return $VenvPython }
    $explicit = Get-EnvValue 'PYTHON_EXE'
    if ($explicit -and (Test-Path $explicit)) { return $explicit }

    $candidates = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python312\python.exe",
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            # Microsoft Store 스텁(0바이트)은 제외
            if ((Get-Item $c).Length -gt 0) { return $c }
        }
    }
    return $null
}

function Resolve-NodeExe {
    $explicit = Get-EnvValue 'NODE_EXE'
    if ($explicit -and (Test-Path $explicit)) { return $explicit }
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $bundled = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path $bundled) { return $bundled }
    return $null
}

# npm 이 없으면 pnpm(번들 포함)으로 대체한다.
function Resolve-PackageManager {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return @{ Kind = 'npm'; Exe = $npm.Source; Script = $null } }
    $node = Resolve-NodeExe
    $pnpm = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.cjs"
    $pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($pnpmCmd) { return @{ Kind = 'pnpm'; Exe = $pnpmCmd.Source; Script = $null } }
    if ($node -and (Test-Path $pnpm)) { return @{ Kind = 'pnpm-bundled'; Exe = $node; Script = $pnpm } }
    return $null
}

# 주의: 매개변수 이름으로 $Args 를 쓰면 PowerShell 자동 변수와 충돌한다.
function Invoke-PackageManager([hashtable]$Pm, [string[]]$ArgList, [string]$WorkDir) {
    Push-Location $WorkDir
    try {
        if ($Pm.Script) {
            $nodeDir = Split-Path -Parent $Pm.Exe
            $env:PATH = "$nodeDir;$env:PATH"   # postinstall 이 node 를 찾을 수 있게 한다
            & $Pm.Exe $Pm.Script @ArgList
        } else {
            & $Pm.Exe @ArgList
        }
        if ($LASTEXITCODE -ne 0) { throw "패키지 매니저 명령 실패: $($ArgList -join ' ')" }
    } finally { Pop-Location }
}

function Get-AppPort {
    return [int](Get-EnvValue 'APP_PORT' '8080')
}

function Get-AppHost {
    return (Get-EnvValue 'APP_HOST' '127.0.0.1')
}

# 0.0.0.0 은 바인딩 주소일 뿐 접속 주소가 아니므로 루프백으로 바꾼다.
function Get-ApiBaseUrl {
    $h = Get-AppHost
    if ($h -eq '0.0.0.0' -or $h -eq '::') { $h = '127.0.0.1' }
    $scheme = if ((Get-EnvValue 'SSL_CERTFILE') -and (Get-EnvValue 'SSL_KEYFILE')) { 'https' } else { 'http' }
    return "$($scheme)://$($h):$(Get-AppPort)"
}

function Get-HealthUrl {
    return "$(Get-ApiBaseUrl)/api/v1/health"
}

# 운영 스크립트(backup/restore)가 감사 로그에 흔적을 남긴다. 실패해도 작업 자체는 계속한다.
function Write-SystemAudit([string]$Action, [hashtable]$Detail) {
    $health = Test-AppHealth 2
    if (-not $health) {
        Write-Warn2 '앱이 실행 중이 아니어서 감사 로그에 기록하지 못했습니다(작업 자체는 정상).'
        return $false
    }
    try {
        $body = @{ action = $Action; detail = $Detail } | ConvertTo-Json -Depth 5
        Invoke-RestMethod -Method Post -Uri "$(Get-ApiBaseUrl)/api/v1/audit/system-event" `
            -ContentType 'application/json; charset=utf-8' -TimeoutSec 5 -Body $body | Out-Null
        Write-Ok '감사 로그 기록 완료'
        return $true
    } catch {
        Write-Warn2 "감사 로그 기록 실패: $($_.Exception.Message)"
        return $false
    }
}

function Test-AppHealth([int]$TimeoutSec = 3) {
    try {
        $resp = Invoke-RestMethod -Uri (Get-HealthUrl) -TimeoutSec $TimeoutSec -Method Get
        return $resp
    } catch { return $null }
}

function Get-AppProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content $PidFile -Raw).Trim()
    if (-not $raw) { return $null }
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    return $proc
}

function Test-IsPostgres {
    $url = Get-EnvValue 'DATABASE_URL'
    return ($url -like 'postgres*')
}
