# 공통 유틸. 각 스크립트에서 dot-source 한다.
# Windows PowerShell 5.1 및 PowerShell 7 모두에서 동작한다.

$ErrorActionPreference = 'Stop'

# 한국어 Windows 의 기본 ANSI 코드페이지는 cp949 다. 일부 라이브러리(alembic 등)가
# encoding="locale" 로 설정파일을 읽으므로, Python 을 UTF-8 모드로 고정해 둔다.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 대상 PC 에 다른 Python 이 있어도 섞이지 않게 — 그쪽 경로 · 사용자 site-packages 를 보지 않는다
Remove-Item env:PYTHONHOME, env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'

$script:Root = Split-Path -Parent $PSScriptRoot
$script:BackendDir = Join-Path $Root 'backend'
$script:FrontendDir = Join-Path $Root 'frontend'
$script:RunDir = Join-Path $Root 'run'
$script:LogDir = Join-Path $Root 'logs'
$script:DataDir = Join-Path $Root 'data'
$script:BackupDir = Join-Path $Root 'backup'
$script:EnvFile = Join-Path $Root '.env'
$script:PidFile = Join-Path $RunDir 'app.pid'
$script:StopFlag = Join-Path $RunDir 'stop.flag'
$script:RuntimeDir = Join-Path $Root 'runtime'
$script:VenvPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
# 설치 패키지는 가상환경 대신 의존성까지 담은 Python 을 runtime\python 에 넣어 온다(인터넷 없는 PC).
# 개발 PC 는 backend\.venv 를 쓴다. 이후 스크립트는 모두 $AppPython 으로 부른다.
$script:BundledPython = Join-Path $RuntimeDir 'python\python.exe'
$script:AppPython = if (Test-Path $BundledPython) { $BundledPython } else { $VenvPython }
$script:BundledPgBin = Join-Path $RuntimeDir 'pgsql\bin'
# 서비스 모드(설치 프로그램이 관리자 권한으로 등록): 부팅 시 앱을 띄우는 예약 작업과 매일 백업 작업
$script:AppTaskName = 'SOC-Handover'
$script:BackupTaskName = 'SOC-Handover-Backup'

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
    if (Test-Path $BundledPython) { return $BundledPython }
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

function Test-IsAppPython($Proc) {
    # 이 설치본의 python 인가. 경로를 읽을 수 없는 프로세스(시스템 프로세스)는 아니다.
    if (-not $Proc) { return $false }
    if ($Proc.ProcessName -notmatch '^pythonw?$') { return $false }
    $path = $Proc.Path
    if (-not $path) { return $false }
    return ([IO.Path]::GetFullPath($path) -eq [IO.Path]::GetFullPath($AppPython))
}

function Get-AppProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content $PidFile -Raw).Trim()
    if (-not $raw) { return $null }
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    # PC 가 비정상 종료되면 PID 파일이 남고, 재부팅 뒤 그 번호를 svchost 같은 시스템
    # 프로세스가 쓰고 있을 수 있다. 우리 서버가 아니면 없는 것으로 본다 — stop.ps1 이
    # 엉뚱한 프로세스를 종료하지 않게 하는 안전장치다.
    if (-not (Test-IsAppPython $proc)) { return $null }
    return $proc
}

function Test-IsPostgres {
    $url = Get-EnvValue 'DATABASE_URL'
    return ($url -like 'postgres*')
}

# uvicorn 인자 — start.ps1(수동) 과 service-run.ps1(서비스) 이 같은 값을 쓴다
function Get-UvicornArgs {
    $a = @('-m', 'uvicorn', 'app.main:app', '--host', (Get-AppHost), '--port', "$(Get-AppPort)")
    $cert = Get-EnvValue 'SSL_CERTFILE'
    $key = Get-EnvValue 'SSL_KEYFILE'
    if ($cert -and $key -and (Test-Path $cert) -and (Test-Path $key)) {
        $a += @('--ssl-certfile', $cert, '--ssl-keyfile', $key)
    }
    return $a
}

# 앱 Python 을 실행하고 출력을 받는다. Python 은 UTF-8 로 쓰는데 PowerShell 은 콘솔 코드페이지(cp949)로
# 읽어 한글이 깨지므로, 받는 동안만 UTF-8 로 바꾼다.
function Invoke-AppPythonCapture([string[]]$ArgList) {
    $prev = $null
    try { $prev = [Console]::OutputEncoding; [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch { }
    try { return (& $AppPython @ArgList) }
    finally { if ($prev) { try { [Console]::OutputEncoding = $prev } catch { } } }
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------------------------------------------------------- PostgreSQL 도구 · 함께 설치한 DB

# PG_BIN(.env) → 설치 패키지의 runtime\pgsql → 일반 설치 경로 → PATH
function Resolve-PgBin {
    $explicit = Get-EnvValue 'PG_BIN'
    if ($explicit -and (Test-Path (Join-Path $explicit 'pg_dump.exe'))) { return $explicit }
    if (Test-Path (Join-Path $BundledPgBin 'pg_dump.exe')) { return $BundledPgBin }
    foreach ($v in @(17, 16, 15)) {
        $p = "C:\Program Files\PostgreSQL\$v\bin"
        if (Test-Path (Join-Path $p 'pg_dump.exe')) { return $p }
    }
    $cmd = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path -Parent $cmd.Source) }
    return $null
}

# 설치 프로그램이 DB 까지 함께 설치했는가(.env PG_BUNDLED=true). 아니면 DB 는 따로 운영하는 것으로 본다.
function Test-BundledDb { return ((Get-EnvValue 'PG_BUNDLED') -eq 'true') }
function Get-PgData {
    $d = Get-EnvValue 'PG_DATA'
    if ($d) { return $d }
    return (Join-Path $DataDir 'pgdata')
}
function Get-PgPort { return [int](Get-EnvValue 'PG_PORT' '5432') }

function Test-DbReady {
    $bin = Resolve-PgBin
    if (-not $bin) { return $false }
    & (Join-Path $bin 'pg_isready.exe') -q -h 127.0.0.1 -p (Get-PgPort) 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# DB 가 Windows 서비스로 등록되어 있으면 그 서비스(서비스 모드), 없으면 $null(수동 모드)
function Get-DbService {
    $name = Get-EnvValue 'PG_SERVICE'
    if (-not $name) { return $null }
    return (Get-Service -Name $name -ErrorAction SilentlyContinue)
}

# pg_ctl 은 띄운 postgres 에 자기 표준출력을 물려 준다. 파이프로 받으면 postgres 가 끝날 때까지
# 호출한 쪽이 멈추므로(실측) 출력은 항상 파일로 받는다.
# 또, 띄워진 postgres 가 그 출력 파일을 계속 쥐고 있으므로 호출마다 새 파일을 쓴다(최근 20회분만 남김).
function Invoke-PgCtl([string[]]$ArgList) {
    $bin = Resolve-PgBin
    $dir = Join-Path $LogDir 'pg_ctl'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $out = Join-Path $dir "$($ArgList[0])_$stamp.out.log"
    $err = Join-Path $dir "$($ArgList[0])_$stamp.err.log"
    # -Wait 는 쓰지 않는다: Windows PowerShell 5.1 의 -Wait 는 자손 프로세스(= 계속 떠 있는 postgres)까지 기다린다.
    # pg_ctl 자신만 기다린다(-w 로 준비될 때까지 기다린 뒤 끝난다). Handle 을 먼저 잡아야 ExitCode 가 남는다.
    $p = Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') -ArgumentList $ArgList -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle
    $p.WaitForExit()
    Get-ChildItem $dir -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 40 | Remove-Item -ErrorAction SilentlyContinue
    return $p.ExitCode
}

function Start-BundledDb {
    if (-not (Test-BundledDb)) { return $true }
    if (Test-DbReady) { return $true }
    $svc = Get-DbService
    if ($svc) {
        try { Start-Service -Name $svc.Name -ErrorAction Stop }
        catch {
            Write-Err "DB 서비스($($svc.Name))를 시작하지 못했습니다: $($_.Exception.Message)"
            Write-Host '    관리자 권한으로 다시 실행하십시오(시작 파일은 자동으로 권한을 요청합니다).'
            return $false
        }
    } else {
        $log = Join-Path $LogDir 'postgresql.log'
        $code = Invoke-PgCtl @('start', '-D', "`"$(Get-PgData)`"", '-l', "`"$log`"", '-w', '-t', '90')
        if ($code -ne 0) {
            Write-Err "DB 를 시작하지 못했습니다(pg_ctl $code). 로그: $log"
            return $false
        }
    }
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-DbReady) { return $true }
        Start-Sleep -Seconds 1
    }
    Write-Err 'DB 가 60초 안에 준비되지 않았습니다.'
    return $false
}

function Stop-BundledDb {
    if (-not (Test-BundledDb)) { return $true }
    $svc = Get-DbService
    if ($svc) {
        if ($svc.Status -ne 'Stopped') { Stop-Service -Name $svc.Name -ErrorAction Stop }
        return $true
    }
    if (-not (Test-DbReady)) { return $true }
    $code = Invoke-PgCtl @('stop', '-D', "`"$(Get-PgData)`"", '-m', 'fast', '-w', '-t', '60')
    return ($code -eq 0)
}

# 서비스 모드로 설치되었는가 — 설치 프로그램이 설치 폴더에 SERVICE_MODE 표시 파일을 둔다.
# (관리자 권한이 없는 창에서는 SYSTEM 예약 작업이 안 보일 수 있어, 작업 존재 여부로 판단하지 않는다)
function Test-ServiceMode { return (Test-Path (Join-Path $Root 'SERVICE_MODE')) }

# 앱 예약 작업(서비스 모드). 관리자 권한이 없으면 $null 일 수 있다.
function Get-AppTask {
    return (Get-ScheduledTask -TaskName $AppTaskName -ErrorAction SilentlyContinue)
}

# DATABASE_URL(postgresql+psycopg://user:pw@host:port/db) 을 libpq 환경변수로 푼다.
# 비밀번호를 명령줄 인자(URL)로 넘기면 같은 PC 의 다른 사용자가 프로세스 목록에서 볼 수 있다 — 환경변수로만 넘긴다.
# -Superuser: 함께 설치한 DB 의 관리 계정(postgres)으로 — 복구처럼 DB 를 새로 만들 때.
function Use-PgCredential([switch]$Superuser) {
    $url = Get-EnvValue 'DATABASE_URL'
    if ($url -notmatch '^postgres(ql)?(\+\w+)?://(?<user>[^:@/]+)(:(?<pw>[^@]*))?@(?<host>[^:/]+)(:(?<port>\d+))?/(?<db>[^?]+)') {
        throw 'DATABASE_URL 이 PostgreSQL 형식이 아닙니다.'
    }
    $env:PGHOST = $Matches['host']
    $env:PGPORT = $(if ($Matches['port']) { $Matches['port'] } else { '5432' })
    $env:PGDATABASE = $Matches['db']
    if ($Superuser) {
        $env:PGUSER = 'postgres'
        $env:PGPASSWORD = Get-EnvValue 'PG_SUPERUSER_PASSWORD'
    } else {
        $env:PGUSER = [Uri]::UnescapeDataString($Matches['user'])
        $env:PGPASSWORD = [Uri]::UnescapeDataString($Matches['pw'])
    }
    # 도구 메시지를 영어로 — 한국어 Windows 콘솔(cp949)에서 UTF-8 메시지가 깨지는 것을 피한다
    $env:LC_MESSAGES = 'C'
    return @{ Db = $Matches['db']; User = [Uri]::UnescapeDataString($Matches['user']) }
}

function Clear-PgCredential {
    Remove-Item env:PGPASSWORD, env:PGUSER, env:PGHOST, env:PGPORT, env:PGDATABASE -ErrorAction SilentlyContinue
}
