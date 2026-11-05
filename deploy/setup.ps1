<#
.SYNOPSIS
    SOC 인수인계 플랫폼 — 오프라인 설치 · 업그레이드 (Windows 10/11 64비트)

.DESCRIPTION
    인터넷 없이 설치합니다. 필요한 것은 모두 이 패키지 안에 있습니다.
      · Python 3.12 + 서버 라이브러리   (runtime\python)
      · PostgreSQL 16                    (runtime\pgsql)
      · Visual C++ 재배포 패키지         (setup\vc_redist.x64.exe — 없을 때만 설치)
      · 빌드된 화면(UI)                   (frontend\dist)

    INSTALL.cmd 를 더블클릭하면 관리자 권한을 요청한 뒤 이 스크립트를 실행합니다.
    이미 설치된 폴더에 다시 실행하면 업그레이드합니다(데이터 · 설정 유지, 먼저 DB 백업).

    기본(서비스 모드)
      · DB 를 Windows 서비스(SOC-Handover-DB)로 등록 — 부팅 시 자동 시작
      · 앱을 예약 작업(SOC-Handover)으로 등록 — 부팅 시 SYSTEM 권한으로 자동 시작, 죽으면 다시 띄움
      · 매일 03:00 백업 예약 작업(SOC-Handover-Backup)
      · Windows 방화벽에 앱 포트 인바운드 허용
    -Manual(수동 모드)
      · 위 등록을 하지 않습니다. start.cmd 로 켜고 stop.cmd 로 끕니다(로그오프하면 멈춤).

.PARAMETER InstallDir
    설치 폴더. 기본 C:\SOC-Handover. 영문 · 숫자 경로만(공백 · 한글 불가).

.PARAMETER AppPort
    화면 · API 포트. 기본 8080.

.PARAMETER DbPort
    DB 포트. 기본은 5432 부터 비어 있는 포트를 고릅니다(이미 다른 PostgreSQL 이 있어도 충돌하지 않게).

.PARAMETER Manual
    수동 모드로 설치합니다(자동 시작 · 방화벽 · 서비스 등록 안 함).

.PARAMETER NoFirewall
    방화벽 규칙을 만들지 않습니다(이 PC 에서만 접속하거나 IT 담당자가 따로 여는 경우).

.PARAMETER Yes
    시작 확인 질문을 생략합니다. 관리자 비밀번호는 환경변수 SOC_ADMIN_PASSWORD 가 있으면 그것을 씁니다(무인 설치 · 시험용).

.EXAMPLE
    INSTALL.cmd
    INSTALL.cmd -InstallDir D:\SOC-Handover -AppPort 8090
    INSTALL.cmd -Manual
#>
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\SOC-Handover',
    [int]$AppPort = 8080,
    [int]$DbPort = 0,
    [switch]$Manual,
    [switch]$NoFirewall,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Remove-Item env:PYTHONHOME, env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'

$BundleRoot = Split-Path -Parent $PSScriptRoot
$Payload = Join-Path $BundleRoot 'payload'
$Version = (Get-Content (Join-Path $BundleRoot 'VERSION.txt') -TotalCount 1 -ErrorAction SilentlyContinue)
if (-not $Version) { $Version = '?' }

$DbService = 'SOC-Handover-DB'
$AppTask = 'SOC-Handover'
$BackupTask = 'SOC-Handover-Backup'
$FirewallRule = 'SOC-Handover-App'

$transcript = Join-Path ([IO.Path]::GetTempPath()) ("soc-handover-install-{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
try { Start-Transcript -Path $transcript -Force | Out-Null } catch { }

function Step([string]$m) { Write-Host "`n▶ $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "  ✔ $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail([string]$m) { throw $m }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-PortFree([int]$Port) {
    return -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function New-Secret([int]$Length) {
    # 영문 대소문자 · 숫자만 — URL · SQL · .env 어디에 넣어도 따옴표 처리가 필요 없다
    $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] $Length
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function New-VaultKey {
    # 장비 비밀번호 보관용 키 — 32바이트 난수를 base64(url) 로. app/core/crypto.py 가 이 형식을 읽는다.
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([Convert]::ToBase64String($bytes)).Replace('+', '-').Replace('/', '_')
}

function Invoke-Quiet([string]$Exe, [string[]]$ArgList, [string]$LogName) {
    # 자식이 표준출력 핸들을 물고 있어도(pg_ctl) 멈추지 않도록 출력은 파일로 받는다
    $logDir = Join-Path $InstallDir 'logs'
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
        # 실행 자체가 막힌 경우(예: Smart App Control) — 종료코드가 없다
        return @{ Code = -2; Out = $out; Err = $err; Message = $_.Exception.Message }
    }
}

# Smart App Control(Windows 11): 0 끔 · 1 켬(적용) · 2 평가 중.
# 켜져 있으면 서명되지 않은 실행 파일을 막는다 — PostgreSQL 배포 파일(EnterpriseDB)은 서명이 없다.
function Get-SmartAppControlState {
    $v = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState
    if ($null -eq $v) { return 0 }
    return [int]$v
}

$SacHelp = @(
    '    Smart App Control 이 서명 없는 프로그램을 막고 있습니다. 다음 중 하나로 해결하십시오.',
    '      1) Windows 보안 → 앱 및 브라우저 컨트롤 → Smart App Control 설정 → "끄기"',
    '         (끄면 다시 켤 수 없습니다. 관리 대상 사내 PC 는 보통 꺼져 있습니다)',
    '      2) 사내 코드서명 인증서가 있으면 runtime\pgsql\bin\*.exe 에 서명한 뒤 다시 설치',
    '      3) Smart App Control 이 꺼져 있는 다른 PC 에 설치'
) -join "`n"

function Read-EnvFile([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -gt 0) { $map[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim() }
    }
    return $map
}

function Set-Acl-Private([string]$Path, [switch]$DbService) {
    # SYSTEM · Administrators · 설치한 사용자만(+ DB 서비스 계정). 다른 사용자는 읽지도 못한다.
    $grants = @('*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', "*$($script:UserSid):(OI)(CI)M")
    if ($DbService) { $grants += '*S-1-5-20:(OI)(CI)F' }   # NT AUTHORITY\NetworkService
    # 폴더에만 설정하고 안의 파일은 그것을 물려받게 한다. /T 로 파일마다 (OI)(CI) 를 주면 파일의 ACL 이
    # 비어 버려 아무도 못 읽는다(실측: postgresql.conf Permission denied).
    $args2 = @($Path, '/inheritance:r', '/grant:r') + $grants + @('/C', '/Q')
    & icacls.exe @args2 | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "권한 설정 경고($Path): icacls $LASTEXITCODE" }
    if (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue) {
        & icacls.exe (Join-Path $Path '*') /reset /T /C /Q | Out-Null
    }
    $global:LASTEXITCODE = 0
}

$script:UserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$exitCode = 0
$createdAdmin = $false

try {
    Write-Host '=====================================================' -ForegroundColor White
    Write-Host " SOC 교대근무 인수인계 플랫폼 설치 (버전 $Version)" -ForegroundColor White
    Write-Host '=====================================================' -ForegroundColor White

    # ============================================================ 1. 사전 점검
    Step '사전 점검'

    if (-not [Environment]::Is64BitOperatingSystem) { Fail '64비트 Windows 가 필요합니다.' }
    $os = [Environment]::OSVersion.Version
    $caption = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption
    if ($os.Major -lt 10) { Fail "Windows 10 이상이 필요합니다(현재: $caption)." }
    Ok "운영체제: $caption (빌드 $($os.Build), 64비트)"
    if ($PSVersionTable.PSVersion.Major -lt 5) { Fail 'PowerShell 5.1 이상이 필요합니다.' }

    $isAdmin = Test-Admin
    $sacState = Get-SmartAppControlState
    if ($sacState -ne 0) {
        Warn "Smart App Control 이 $(if ($sacState -eq 1) {'켜져'} else {'평가 모드로'}) 있습니다 — 서명 없는 PostgreSQL 실행 파일이 막힐 수 있습니다(설치 중 확인합니다)."
    }

    if (-not (Test-Path (Join-Path $Payload 'runtime\python\python.exe'))) {
        Fail "설치 파일이 온전하지 않습니다(payload 없음). 압축을 모두 푼 폴더에서 실행하십시오: $BundleRoot"
    }

    $InstallDir = [IO.Path]::GetFullPath($InstallDir.TrimEnd('\'))
    if ($InstallDir -notmatch '^[A-Za-z]:\\[A-Za-z0-9_.\-\\]+$') {
        Fail "설치 경로는 영문 · 숫자 · - _ . 만 쓸 수 있습니다(공백 · 한글 불가): $InstallDir"
    }
    if ($env:OneDrive -and $InstallDir.StartsWith($env:OneDrive, [StringComparison]::OrdinalIgnoreCase)) {
        Fail 'OneDrive 동기화 폴더에는 설치할 수 없습니다(DB 파일이 동기화되며 깨질 수 있음).'
    }
    if ($InstallDir.StartsWith($BundleRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Fail '설치 파일을 푼 폴더 안에는 설치할 수 없습니다. 다른 경로를 지정하십시오.'
    }

    # VERSION.txt 는 설치가 끝까지 성공했을 때만 쓴다 — 있으면 업그레이드.
    # .env 만 있으면 지난 설치가 중간에 멈춘 것 — 그 설정(비밀번호 · 포트)을 그대로 이어서 진행한다.
    $upgrade = Test-Path (Join-Path $InstallDir 'VERSION.txt')
    $hasEnv = Test-Path (Join-Path $InstallDir '.env')
    $oldEnv = if ($hasEnv) { Read-EnvFile (Join-Path $InstallDir '.env') } else { @{} }
    if ($hasEnv) {
        if ($upgrade) {
            $oldVersion = (Get-Content (Join-Path $InstallDir 'VERSION.txt') -TotalCount 1 -ErrorAction SilentlyContinue)
            Ok "기존 설치 발견 → 업그레이드 ($oldVersion → $Version). 데이터 · 설정은 그대로 둡니다."
        } else {
            # 지난 설치가 중간에 멈췄거나, 데이터를 남기고 제거한 뒤 다시 설치하는 경우
            Ok '이전 설정(.env)과 데이터를 찾았습니다 → 같은 설정 · 데이터로 이어서 진행합니다.'
        }
        if ($oldEnv['APP_PORT']) { $AppPort = [int]$oldEnv['APP_PORT'] }
        if ($oldEnv['PG_PORT']) { $DbPort = [int]$oldEnv['PG_PORT'] }
        # 설치 방식은 처음 설치한 대로 따른다(-Manual 을 다시 주지 않아도 된다)
        $Manual = -not $oldEnv['PG_SERVICE']
    }
    if (-not $Manual -and -not $isAdmin) {
        Fail '관리자 권한이 필요합니다. INSTALL.cmd 를 더블클릭하십시오(권한 요청 창에서 "예"). 관리자 권한이 없으면 INSTALL.cmd -Manual'
    }
    Ok $(if ($Manual) { '설치 방식: 수동 모드(자동 시작 없음)' } else { '설치 방식: 서비스 모드(부팅 시 자동 시작)' })

    $drive = Get-PSDrive -Name $InstallDir.Substring(0, 1) -ErrorAction SilentlyContinue
    if ($drive -and $drive.Free -lt 3GB) {
        Fail "디스크 여유 공간이 부족합니다($([math]::Round($drive.Free/1GB,1))GB). 3GB 이상 필요합니다."
    }
    Ok "설치 경로: $InstallDir (여유 $([math]::Round($drive.Free/1GB,1))GB)"

    if (-not $hasEnv) {
        if (-not (Test-PortFree $AppPort)) { Fail "포트 $AppPort 를 다른 프로그램이 쓰고 있습니다. INSTALL.cmd -AppPort 8090 처럼 다른 포트를 지정하십시오." }
        if ($DbPort -eq 0) {
            foreach ($p in 5432..5449) { if (Test-PortFree $p) { $DbPort = $p; break } }
            if ($DbPort -eq 0) { Fail 'DB 에 쓸 빈 포트(5432~5449)가 없습니다. -DbPort 로 지정하십시오.' }
        } elseif (-not (Test-PortFree $DbPort)) { Fail "DB 포트 $DbPort 를 다른 프로그램이 쓰고 있습니다." }
    }
    Ok "포트: 화면 · API $AppPort / DB $DbPort (DB 는 이 PC 안에서만 접속)"

    if (-not $upgrade -and -not $Yes) {
        Write-Host ''
        $answer = Read-Host '위 내용으로 설치할까요? (Y/N)'
        if ($answer -notmatch '^[Yy]') { Write-Host '취소했습니다.'; $exitCode = 2; return }
    }

    # ============================================================ 2. 설치 파일 검사
    Step '설치 파일 검사 (복사 중 손상 여부)'
    $manifest = Join-Path $BundleRoot 'MANIFEST.sha256'
    if (-not (Test-Path $manifest)) { Fail 'MANIFEST.sha256 이 없습니다. 패키지를 다시 받으십시오.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    $bad = New-Object System.Collections.Generic.List[string]
    $lines = Get-Content $manifest -Encoding UTF8
    $n = 0
    foreach ($line in $lines) {
        if (-not $line) { continue }
        $hash = $line.Substring(0, 64); $rel = $line.Substring(66)
        $path = Join-Path $BundleRoot $rel
        if (-not (Test-Path -LiteralPath $path)) { $bad.Add("없음: $rel"); continue }
        $fs = [IO.File]::OpenRead($path)
        try { $h = -join ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString('x2') }) } finally { $fs.Dispose() }
        if ($h -ne $hash) { $bad.Add("손상: $rel") }
        $n++
        if (($n % 1000) -eq 0) { Write-Host "    $n / $($lines.Count)" }
    }
    if ($bad.Count) {
        $bad | Select-Object -First 10 | ForEach-Object { Warn $_ }
        Fail "설치 파일 $($bad.Count)개가 없거나 손상되었습니다. zip 을 다시 복사해 압축을 푸십시오."
    }
    Ok "$n 개 파일 이상 없음"

    # 인터넷에서 받은 zip 을 풀면 파일마다 '차단' 표시가 붙는다(Mark of the Web) — 해제한다
    Get-ChildItem -LiteralPath $BundleRoot -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

    # ============================================================ 3. Visual C++ 런타임
    Step 'Visual C++ 런타임 (PostgreSQL 에 필요)'
    $vcExe = Join-Path $PSScriptRoot 'vc_redist.x64.exe'
    $bundledVc = [version]((Get-Item $vcExe).VersionInfo.ProductVersion)
    $vcKey = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64' -ErrorAction SilentlyContinue
    $installedVc = $null
    if ($vcKey -and $vcKey.Installed -eq 1) { $installedVc = [version]("$($vcKey.Major).$($vcKey.Minor).$($vcKey.Bld)") }
    if ($installedVc -and $installedVc -ge [version]("$($bundledVc.Major).$($bundledVc.Minor).$($bundledVc.Build)")) {
        Ok "이미 설치됨 ($installedVc)"
    } else {
        if (-not $isAdmin) { Fail "Visual C++ 런타임 설치가 필요합니다($(if ($installedVc) {"현재 $installedVc"} else {'없음'})). 관리자 권한으로 INSTALL.cmd 를 실행하십시오." }
        Write-Host "    설치 중 ($bundledVc)..."
        $p = Start-Process -FilePath $vcExe -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru
        switch ($p.ExitCode) {
            0 { Ok '설치 완료' }
            1638 { Ok '더 새 버전이 이미 있습니다' }
            3010 { Warn '설치 완료 — 일부 파일은 재부팅 후 교체됩니다. 설치가 실패하면 재부팅 후 다시 실행하십시오.' }
            default { Fail "Visual C++ 런타임 설치 실패 (코드 $($p.ExitCode))" }
        }
    }

    # ============================================================ 4. 업그레이드: 멈추고 백업
    if ($upgrade) {
        Step '기존 서비스 중지 · 백업'
        $stopPs = Join-Path $InstallDir 'stop.ps1'
        $backupPs = Join-Path $InstallDir 'backup.ps1'
        # 주의: DB 를 띄울 수 있는 자식의 출력을 파이프로 받지 않는다 — postgres 가 파이프를 물고 있어 설치가 멈춘다
        if (Test-Path $stopPs) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopPs -KeepDb }
        # 백업은 DB 가 켜져 있어야 한다
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ". '$InstallDir\scripts\common.ps1'; Import-DotEnv | Out-Null; if (-not (Start-BundledDb)) { exit 1 }"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupPs -KeepDays 3650
        if ($LASTEXITCODE -ne 0) { Fail '업그레이드 전 백업에 실패했습니다. 설치를 멈춥니다(기존 설치는 그대로입니다).' }
        Ok '업그레이드 전 백업 완료'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopPs -IncludeDb
        Ok '기존 서비스 중지'
    }

    # ============================================================ 5. 파일 복사
    Step '파일 복사'
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    foreach ($d in @('backend', 'frontend', 'runtime', 'scripts', 'docs')) {
        $src = Join-Path $Payload $d
        if (-not (Test-Path $src)) { continue }
        # /MIR: 이전 버전에만 있던 파일은 지운다(데이터 폴더는 대상이 아님)
        $null = & robocopy.exe $src (Join-Path $InstallDir $d) /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:2
        if ($LASTEXITCODE -ge 8) { Fail "파일 복사 실패: $d (robocopy $LASTEXITCODE)" }
    }
    $null = & robocopy.exe $Payload $InstallDir *.ps1 *.cmd *.txt *.md /NFL /NDL /NJH /NJS /NP /R:2 /W:2
    if ($LASTEXITCODE -ge 8) { Fail "파일 복사 실패 (robocopy $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
    foreach ($d in @('data', 'data\attachments', 'backup', 'logs', 'run')) {
        New-Item -ItemType Directory -Path (Join-Path $InstallDir $d) -Force | Out-Null
    }
    Ok "복사 완료 → $InstallDir"

    # 권한은 매번 다시 맞춘다(중간에 멈춘 설치 · 사람이 바꾼 권한도 되돌린다).
    # 프로그램 폴더: 사용자는 읽기만. 데이터 · 백업 · 로그 · 실행 폴더: 관리자 · 설치한 사용자만.
    & icacls.exe $InstallDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' `
        '*S-1-5-32-545:(OI)(CI)RX' "*$($script:UserSid):(OI)(CI)M" /C /Q | Out-Null
    foreach ($d in @('data', 'backup', 'logs', 'run')) { Set-Acl-Private (Join-Path $InstallDir $d) }
    Ok '폴더 권한 (데이터 · 백업 · 로그: 관리자 · 설치한 사용자만)'

    $py = Join-Path $InstallDir 'runtime\python\python.exe'
    $pgBin = Join-Path $InstallDir 'runtime\pgsql\bin'
    $pgData = Join-Path $InstallDir 'data\pgdata'

    # 번들 PostgreSQL 이 이 PC 에서 실제로 실행되는지 먼저 확인한다(런타임 DLL · 실행 차단 정책).
    # 서버(postgres)와 시작 도구(pg_ctl)를 모두 본다 — Smart App Control 은 파일마다 따로 막는다(실측).
    foreach ($exe in @('postgres.exe', 'pg_ctl.exe')) {
        $check = Invoke-Quiet (Join-Path $pgBin $exe) @('--version') "check-$($exe -replace '\.exe$', '')"
        if ($check.Code -ne 0) {
            if ($check.Message) { Warn $check.Message }
            $sac = Get-SmartAppControlState
            if ($sac -ne 0 -or $check.Code -eq -2) {
                Write-Host $SacHelp -ForegroundColor Yellow
                Fail "$exe 실행이 차단되었습니다(Smart App Control 상태 $sac)."
            }
            Fail "$exe 실행 확인 실패(코드 $($check.Code)). Visual C++ 런타임 설치 여부를 확인하고, 재부팅 후 다시 실행하십시오. 로그: $($check.Err)"
        }
        if ($exe -eq 'postgres.exe') { Ok "PostgreSQL: $((Get-Content $check.Out -TotalCount 1).Trim())" }
    }
    $pyVer = & $py -c "import sys; print(sys.version.split()[0])"
    if ($LASTEXITCODE -ne 0) { Fail 'Python 실행 확인 실패.' }
    Ok "Python: $pyVer"

    # ============================================================ 6. 권한 · 설정 파일
    if (-not $hasEnv) {
        Step '설정 파일(.env)'
        $appPw = New-Secret 32
        $suPw = New-Secret 32
        $secretKey = New-Secret 64
        $envLines = @(
            '# SOC 인수인계 플랫폼 설정 — 설치 프로그램이 만들었습니다. 비밀값이 들어 있으니 공유하지 마십시오.',
            "# 설치: $(Get-Date -Format 'yyyy-MM-dd HH:mm') / 버전 $Version",
            'APP_ENV=prod',
            'APP_HOST=0.0.0.0',
            "APP_PORT=$AppPort",
            'ENABLE_DOCS=false',
            "SECRET_KEY=$secretKey",
            '# 장비 비밀번호 보관용 키. 이 값을 잃으면 보관된 비밀번호를 되살릴 수 없습니다.',
            '# (DB 백업에는 암호문만 들어갑니다 — .env 도 따로 안전한 곳에 보관하십시오)',
            "VAULT_KEY=$(New-VaultKey)",
            'ACCESS_TOKEN_MINUTES=15',
            'REFRESH_TOKEN_HOURS=12',
            'COOKIE_SECURE=false',
            '# 로그인 시도 상한(5분 · IP 기준). 한 PC 를 여럿이 돌려 쓰는 교대 콘솔에서',
            '# 교대 시각에 막히면 올리십시오(계정 잠금은 그대로 둡니다).',
            'RATE_LIMIT_LOGIN_PER_5MIN=20',
            '',
            '# 함께 설치한 PostgreSQL (이 PC 안에서만 접속)',
            "DATABASE_URL=postgresql+psycopg://soc_app:$appPw@127.0.0.1:$DbPort/soc_handover",
            'PG_BUNDLED=true',
            "PG_PORT=$DbPort",
            "PG_DATA=$pgData",
            "PG_SUPERUSER_PASSWORD=$suPw"
        )
        if (-not $Manual) { $envLines += "PG_SERVICE=$DbService" }
        $envPath = Join-Path $InstallDir '.env'
        [IO.File]::WriteAllLines($envPath, $envLines, (New-Object Text.UTF8Encoding($false)))
        & icacls.exe $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*$($script:UserSid):M" /Q | Out-Null
        Ok '.env 생성 (비밀값 자동 생성, 관리자 · 설치한 사용자만 읽기)'
    } elseif (-not $oldEnv['VAULT_KEY']) {
        # 1.2.0 에서 생긴 값 — 예전 설치에는 없다. 이미 있으면 **절대 바꾸지 않는다**
        # (바꾸면 그 키로 넣어 둔 비밀번호를 다시 읽을 수 없다).
        Step '설정 파일(.env) — 비밀번호 보관 키 추가'
        $envPath = Join-Path $InstallDir '.env'
        $lines = @(Get-Content $envPath -Encoding UTF8) + @(
            '',
            '# 장비 비밀번호 보관용 키. 이 값을 잃으면 보관된 비밀번호를 되살릴 수 없습니다.',
            "VAULT_KEY=$(New-VaultKey)")
        [IO.File]::WriteAllLines($envPath, $lines, (New-Object Text.UTF8Encoding($false)))
        & icacls.exe $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*$($script:UserSid):M" /Q | Out-Null
        Ok 'VAULT_KEY 생성 (비밀번호 보관 기능에 필요)'
    }

    # common.ps1 을 불러 이후 단계(DB 시작 · 마이그레이션)를 설치본 기준으로 한다
    . (Join-Path $InstallDir 'scripts\common.ps1')
    $ErrorActionPreference = 'Stop'
    Import-DotEnv | Out-Null

    # ============================================================ 7. DB
    Step 'PostgreSQL 준비'
    if (-not (Test-Path (Join-Path $pgData 'PG_VERSION'))) {
        if (Test-Path $pgData) { Remove-Item $pgData -Recurse -Force }
        $pwFile = Join-Path $InstallDir 'run\initdb.pw'
        [IO.File]::WriteAllText($pwFile, (Get-EnvValue 'PG_SUPERUSER_PASSWORD'), (New-Object Text.UTF8Encoding($false)))
        try {
            # 로케일 C + UTF8: Windows 지역 설정(한국어 cp949)과 무관하게 같은 정렬 · 인코딩. 가나다 순서는 유니코드 순서와 같다.
            $r = Invoke-Quiet (Join-Path $pgBin 'initdb.exe') @('-D', "`"$pgData`"", '-U', 'postgres', "--pwfile=`"$pwFile`"",
                '-E', 'UTF8', '--locale=C', '-A', 'scram-sha-256', '--data-checksums') 'initdb'
        } finally { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue }
        if ($r.Code -ne 0) { Get-Content $r.Err -Tail 10 | ForEach-Object { Warn $_ }; Fail "DB 초기화(initdb) 실패. 로그: $($r.Err)" }

        $mem = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
        $shared = if ($mem -ge 16GB) { '1GB' } elseif ($mem -ge 8GB) { '512MB' } else { '256MB' }
        $conf = @(
            '',
            '# ---- SOC 인수인계 설치 프로그램 설정 ----',
            "listen_addresses = '127.0.0.1'",
            "port = $DbPort",
            'max_connections = 50',
            "shared_buffers = $shared",
            "timezone = 'Asia/Seoul'",
            "log_timezone = 'Asia/Seoul'",
            'logging_collector = on',
            "log_directory = 'log'",
            "log_filename = 'postgresql-%a.log'",
            'log_truncate_on_rotation = on',
            'log_rotation_age = 1d',
            'log_rotation_size = 0',
            "lc_messages = 'C'"
        )
        Add-Content -Path (Join-Path $pgData 'postgresql.conf') -Value $conf -Encoding ASCII
        Ok "DB 초기화 완료 (shared_buffers $shared)"
    } else {
        Ok 'DB 데이터 폴더 유지'
    }
    Set-Acl-Private $pgData -DbService:(-not $Manual)

    if (-not $Manual) {
        $svc = Get-Service -Name $DbService -ErrorAction SilentlyContinue
        if (-not $svc) {
            $r = Invoke-Quiet (Join-Path $pgBin 'pg_ctl.exe') @('register', '-N', $DbService, '-U', '"NT AUTHORITY\NetworkService"',
                '-D', "`"$pgData`"", '-S', 'auto', '-w') 'pg_ctl-register'
            if ($r.Code -ne 0) { Get-Content $r.Err -Tail 5 | ForEach-Object { Warn $_ }; Fail 'DB 서비스 등록 실패' }
            & sc.exe description $DbService 'SOC 인수인계 플랫폼 데이터베이스 (PostgreSQL 16)' | Out-Null
            & sc.exe failure $DbService reset= 86400 actions= restart/10000/restart/30000/restart/60000 | Out-Null
            Ok "DB 서비스 등록: $DbService (자동 시작, NetworkService 계정)"
        }
    }
    if (-not (Start-BundledDb)) { Fail "DB 를 시작하지 못했습니다. 로그: $pgData\log" }
    Ok "DB 실행 중 (127.0.0.1:$DbPort)"

    # 앱 전용 계정 · 데이터베이스 — 없을 때만 만든다(중간에 멈춘 설치를 다시 돌려도 안전)
    $psql = Join-Path $pgBin 'psql.exe'
    $info = Use-PgCredential -Superuser
    try {
        $appPw = ((Get-EnvValue 'DATABASE_URL') -split '[:@]')[2]
        $hasRole = (& $psql -X -q -t -A -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = '$($info.User)'") -eq '1'
        $hasDb = (& $psql -X -q -t -A -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$($info.Db)'") -eq '1'
        $sql = @()
        # 비밀번호가 명령줄(프로세스 목록)에 보이지 않게 SQL 은 표준입력으로 넘긴다
        if (-not $hasRole) { $sql += "CREATE ROLE $($info.User) LOGIN PASSWORD '$appPw';" }
        if (-not $hasDb) {
            $sql += "CREATE DATABASE $($info.Db) OWNER $($info.User) ENCODING 'UTF8' TEMPLATE template0;"
            $sql += "REVOKE ALL ON DATABASE $($info.Db) FROM PUBLIC;"
        }
        if ($sql.Count) {
            ($sql -join "`n") | & $psql -X -q -v ON_ERROR_STOP=1 -d postgres -f - | Out-Null
            if ($LASTEXITCODE -ne 0) { Fail 'DB 계정 · 데이터베이스 생성 실패' }
            Ok "앱 전용 계정($($info.User)) · 데이터베이스($($info.Db)) 생성"
        } else {
            Ok "앱 전용 계정 · 데이터베이스 있음"
        }
    } finally { Clear-PgCredential }

    # ============================================================ 8. 스키마 · 기준 데이터 · 관리자
    Step '데이터베이스 구조 (마이그레이션)'
    Push-Location (Join-Path $InstallDir 'backend')
    try {
        # alembic 은 진행 기록을 표준오류로 쓴다 — PS 5.1 에서 2>&1 로 받으면 오류로 멈추므로 파일로 받는다
        $r = Invoke-Quiet $py @('-m', 'alembic', 'upgrade', 'head') 'migrate'
        Get-Content $r.Err -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'Running upgrade' } |
            ForEach-Object { Write-Host "    $($_ -replace '^.*Running upgrade ', '')" }
        if ($r.Code -ne 0) { Get-Content $r.Err -Encoding UTF8 -Tail 15 | ForEach-Object { Warn $_ }; Fail "마이그레이션 실패. 로그: $($r.Err)" }
        Ok '최신 구조 적용'
        $r = Invoke-Quiet $py @('manage.py', 'bootstrap') 'bootstrap'
        if ($r.Code -ne 0) { Get-Content $r.Err -Encoding UTF8 -Tail 15 | ForEach-Object { Warn $_ }; Fail '기준 데이터(상태 · 교대 · 설정) 구성 실패' }
        Ok '기준 데이터 구성'

        $hasAdmin = (& $py -c "from app.core.db import SessionLocal; from app.models.user import User; from sqlalchemy import select; s = SessionLocal(); print('YES' if s.scalar(select(User).where(User.role_code == 'ADMIN')) else 'NO')") -match 'YES'
        if (-not $hasAdmin) {
            Step '관리자 계정 (admin)'
            Write-Host '  비밀번호 규칙: 12자 이상, 영문 대문자 · 소문자 · 숫자 · 특수문자 중 3종 이상, "admin" 포함 불가'
            Write-Host '  처음 로그인하면 한 번 더 바꾸게 됩니다. 입력 내용은 화면에 보이지 않습니다.'
            $preset = [bool]$env:SOC_ADMIN_PASSWORD
            for ($try = 1; $try -le 3; $try++) {
                if (-not $preset) {
                    $a = Read-Host '  관리자 비밀번호' -AsSecureString
                    $b = Read-Host '  한 번 더' -AsSecureString
                    $pa = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($a))
                    $pb = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($b))
                    if ($pa -ne $pb) { Warn '두 입력이 다릅니다.'; continue }
                    $env:SOC_ADMIN_PASSWORD = $pa
                }
                & $py manage.py create-admin --username admin --display-name '시스템 관리자'
                $ok = ($LASTEXITCODE -eq 0)
                if (-not $preset) { Remove-Item env:SOC_ADMIN_PASSWORD -ErrorAction SilentlyContinue }
                if ($ok) { break }
                if ($preset) { Fail '관리자 계정 생성 실패(SOC_ADMIN_PASSWORD 가 규칙에 맞는지 확인)' }
                Warn '다시 입력하십시오.'
            }
            if (-not $ok) { Fail '관리자 계정을 만들지 못했습니다. 설치를 다시 실행하면 이어서 진행합니다.' }
            Ok '관리자 계정 생성: admin'
            $createdAdmin = $true
        } else {
            Ok '관리자 계정 있음(유지)'
        }
    } finally { Pop-Location }

    # ============================================================ 9. 자동 시작 · 백업 · 방화벽
    $marker = Join-Path $InstallDir 'SERVICE_MODE'
    if ($Manual) { Remove-Item $marker -ErrorAction SilentlyContinue }
    if (-not $Manual) {
        Step '자동 시작 · 매일 백업 · 방화벽'
        # start.cmd · stop.cmd 가 관리자 권한을 요청할지 정하는 표시(누구나 읽을 수 있는 설치 폴더 최상위)
        Set-Content -Path $marker -Value "앱: 예약 작업 $AppTask / DB: 서비스 $DbService" -Encoding UTF8
        $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

        $action = New-ScheduledTaskAction -Execute $psExe -WorkingDirectory $InstallDir `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstallDir\scripts\service-run.ps1`""
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $AppTask -Action $action -Trigger $trigger -Principal $principal `
            -Settings $settings -Description 'SOC 인수인계 플랫폼 — 부팅 시 앱 실행(죽으면 다시 띄움)' -Force | Out-Null
        Ok "자동 시작 등록: 작업 스케줄러 '$AppTask'"

        $bAction = New-ScheduledTaskAction -Execute $psExe -WorkingDirectory $InstallDir `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstallDir\backup.ps1`""
        $bTrigger = New-ScheduledTaskTrigger -Daily -At '03:00'
        $bSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $BackupTask -Action $bAction -Trigger $bTrigger -Principal $principal `
            -Settings $bSettings -Description 'SOC 인수인계 플랫폼 — 매일 DB · 첨부 백업(30일 보관)' -Force | Out-Null
        Ok "매일 백업 등록: 03:00 (PC 가 꺼져 있었으면 켜진 뒤 실행)"

        if (-not $NoFirewall) {
            Get-NetFirewallRule -Name $FirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            $profiles = @('Domain', 'Private')
            $publicNet = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' }
            if ($publicNet) {
                $profiles += 'Public'
                Warn "이 PC 의 네트워크가 '공용'으로 분류되어 있어 공용 프로필에도 포트를 엽니다: $(($publicNet.InterfaceAlias) -join ', ')"
            }
            New-NetFirewallRule -Name $FirewallRule -DisplayName "SOC 인수인계 플랫폼 (TCP $AppPort)" `
                -Direction Inbound -Protocol TCP -LocalPort $AppPort -Action Allow -Profile $profiles | Out-Null
            Ok "방화벽 허용: TCP $AppPort ($($profiles -join ', '))"
        }
    }

    # 바탕화면 바로가기(모든 사용자)
    try {
        $desk = [Environment]::GetFolderPath('CommonDesktopDirectory')
        if (-not $isAdmin -or -not $desk) { $desk = [Environment]::GetFolderPath('Desktop') }
        $url = Join-Path $desk 'SOC 인수인계.url'
        Set-Content -Path $url -Value @('[InternetShortcut]', "URL=http://localhost:$AppPort/") -Encoding ASCII
        Ok '바탕화면 바로가기: SOC 인수인계'
    } catch { Warn "바로가기를 만들지 못했습니다: $($_.Exception.Message)" }

    # ============================================================ 10. 시작 · 확인
    Step '시작'
    if (-not $Manual) {
        Remove-Item (Join-Path $InstallDir 'run\stop.flag') -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName $AppTask
    } else {
        # 파이프로 받지 않는다(앱 · DB 가 파이프를 물면 설치가 끝나지 않는다)
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDir 'start.ps1')
    }
    $health = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$AppPort/api/v1/health" -TimeoutSec 2 } catch { }
        if ($health -and $health.database_ok) { break }
    }
    if (-not ($health -and $health.database_ok)) {
        Fail "앱이 60초 안에 응답하지 않습니다. 로그: $InstallDir\logs (service.log, uvicorn.err.log)"
    }
    Ok "응답 확인: 버전 $($health.version), DB $($health.database)"
    # 설치 완료 표시 — 이 파일이 있어야 다음 실행을 '업그레이드'로 본다
    Copy-Item (Join-Path $BundleRoot 'VERSION.txt') (Join-Path $InstallDir 'VERSION.txt') -Force

    $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress)
    $hostName = [Net.Dns]::GetHostName()

    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host $(if ($upgrade) { ' 업그레이드 완료' } else { ' 설치 완료' }) -ForegroundColor Green
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host ''
    Write-Host "  이 PC      : http://localhost:$AppPort/"
    Write-Host "  다른 PC    : http://$($hostName):$AppPort/"
    foreach ($ip in $ips) { Write-Host "               http://$($ip):$AppPort/" }
    if ($createdAdmin) { Write-Host '  로그인     : admin / (방금 정한 비밀번호) — 처음 로그인하면 새 비밀번호로 바꿉니다' }
    Write-Host "  설치 폴더  : $InstallDir"
    if ($Manual) {
        Write-Host '  실행 방식  : 수동 — PC 를 켠 뒤 start.cmd 로 켜고, stop.cmd 로 끕니다'
    } else {
        Write-Host '  실행 방식  : 서비스 — 부팅하면 자동으로 켜집니다. 매일 03:00 백업'
    }
    Write-Host "  사용 설명  : $InstallDir\docs\OPERATIONS.md"
    Write-Host ''
} catch {
    Write-Host ''
    Write-Host "  ✘ 설치를 마치지 못했습니다: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    설치 기록: $transcript" -ForegroundColor Red
    $exitCode = 1
} finally {
    try { Stop-Transcript | Out-Null } catch { }
    if (Test-Path (Join-Path $InstallDir 'logs')) {
        Copy-Item $transcript (Join-Path $InstallDir 'logs') -ErrorAction SilentlyContinue
    }
}
exit $exitCode
