<#
    Windows Sandbox 안에서 자동으로 도는 검증 스크립트 (soc-sandbox-test.wsb 가 실행).

    깨끗한 Windows(아무것도 설치되지 않음) + 인터넷 차단 상태에서
      1) 패키지 압축 풀기 → INSTALL 실행(서비스 모드)
      2) 서비스 · 예약 작업 · 방화벽 · 접속 확인
      3) 중지 · 시작 · 백업 · 상태 확인
    결과는 공유 폴더(C:\share\result)에 남긴다 — 밖에서 그 파일을 읽어 판정한다.
#>
[CmdletBinding()]
param([string]$Share = 'C:\share')

$ErrorActionPreference = 'Continue'
$result = Join-Path $Share 'result'
New-Item -ItemType Directory -Path $result -Force | Out-Null
$log = Join-Path $result 'sandbox-test.log'
Remove-Item (Join-Path $result 'DONE.txt') -ErrorAction SilentlyContinue

function Say([string]$m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $m"
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

function Check([string]$name, [scriptblock]$test) {
    try {
        $value = & $test
        $ok = [bool]$value
        Say "$(if ($ok) { '[OK]  ' } else { '[FAIL]' }) $name : $value"
    } catch {
        Say "[FAIL] $name : $($_.Exception.Message)"
    }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Say '관리자 권한으로 다시 실행합니다(샌드박스 안에서 "예"를 눌러 주십시오).'
    Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $PSCommandPath, '-Share', $Share
    return
}

Say '===== 샌드박스 환경 ====='
$os = Get-CimInstance Win32_OperatingSystem
Say "OS: $($os.Caption) build $($os.BuildNumber) / 64비트=$([Environment]::Is64BitOperatingSystem)"
Say "PowerShell: $($PSVersionTable.PSVersion)"
$vc = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64' -ErrorAction SilentlyContinue
Say "VC++ 런타임(설치 전): $(if ($vc.Installed -eq 1) { "$($vc.Major).$($vc.Minor).$($vc.Bld)" } else { '없음' })"
Say "Python(PATH): $((Get-Command python -ErrorAction SilentlyContinue).Source)"
Say "PostgreSQL(PATH): $((Get-Command psql -ErrorAction SilentlyContinue).Source)"
$sac = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState
Say "Smart App Control 상태: $(if ($null -eq $sac) { '없음(0)' } else { $sac })"
Say "인터넷: $(if (Test-Connection 8.8.8.8 -Count 1 -Quiet -ErrorAction SilentlyContinue) { '연결됨' } else { '차단(의도한 상태)' })"

Say '===== 압축 풀기 ====='
$zip = Get-ChildItem $Share -Filter 'SOC-Handover-*-offline.zip' | Select-Object -First 1
if (-not $zip) { Say '[FAIL] 공유 폴더에 패키지 zip 이 없습니다.'; Set-Content (Join-Path $result 'DONE.txt') 'no-zip'; return }
$work = 'C:\work'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$t = Measure-Command { Expand-Archive $zip.FullName -DestinationPath $work -Force }
$bundle = Get-ChildItem $work -Directory | Select-Object -First 1
Say "압축 해제 $([int]$t.TotalSeconds)초 → $($bundle.FullName)"

Say '===== 설치 (서비스 모드) ====='
$env:SOC_ADMIN_PASSWORD = 'Sandbox#Check2026!qz'
$setup = Join-Path $bundle.FullName 'setup\setup.ps1'
$p = Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup,
    '-InstallDir', 'C:\SOC-Handover', '-AppPort', '8080', '-Yes' `
    -RedirectStandardOutput (Join-Path $result 'setup.out.log') `
    -RedirectStandardError (Join-Path $result 'setup.err.log') -PassThru -NoNewWindow
$null = $p.Handle
$p.WaitForExit(1800000)
Remove-Item env:SOC_ADMIN_PASSWORD
Say "설치 종료 코드: $($p.ExitCode)"

Say '===== 설치 결과 확인 ====='
Check 'DB 서비스 등록 · 실행' { (Get-Service SOC-Handover-DB -ErrorAction SilentlyContinue).Status }
Check 'DB 서비스 자동 시작' { (Get-CimInstance Win32_Service -Filter "Name='SOC-Handover-DB'").StartMode }
Check '앱 예약 작업' { (Get-ScheduledTask -TaskName SOC-Handover -ErrorAction SilentlyContinue).State }
Check '앱 작업 트리거(부팅 시)' { (Get-ScheduledTask -TaskName SOC-Handover -ErrorAction SilentlyContinue).Triggers[0].CimClass.CimClassName }
Check '매일 백업 작업' { (Get-ScheduledTask -TaskName SOC-Handover-Backup -ErrorAction SilentlyContinue).State }
Check '방화벽 규칙' { (Get-NetFirewallRule -Name SOC-Handover-App -ErrorAction SilentlyContinue).Enabled }
Check '바탕화면 바로가기' { Test-Path (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'SOC 인수인계.url') }
Check 'VC++ 런타임(설치 후)' { $v = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64' -ErrorAction SilentlyContinue; "$($v.Major).$($v.Minor).$($v.Bld)" }
Check '데이터 폴더 권한(Users 없음)' { -not ((icacls 'C:\SOC-Handover\data') -join ' ' -match 'BUILTIN\\Users') }

$health = $null
for ($i = 0; $i -lt 30; $i++) {
    try { $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 3 } catch { }
    if ($health) { break }
    Start-Sleep -Seconds 2
}
Say "health: $($health | ConvertTo-Json -Compress)"

Say '===== 화면(UI) 응답 ====='
try {
    $page = Invoke-WebRequest 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 10
    Say "[OK]   첫 화면 $($page.StatusCode) $([int]($page.RawContentLength/1KB))KB"
    $asset = ([regex]::Match($page.Content, 'src="(/assets/[^"]+\.js)"')).Groups[1].Value
    $js = Invoke-WebRequest "http://127.0.0.1:8080$asset" -UseBasicParsing -TimeoutSec 20
    Say "[OK]   화면 자원 $asset $([int]($js.RawContentLength/1KB))KB"
} catch { Say "[FAIL] 화면 응답: $($_.Exception.Message)" }

Say '===== 로그인 · 데이터 · 백업 ====='
try {
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $login = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/auth/login' -Method Post -WebSession $s `
        -ContentType 'application/json' -Body '{"username":"admin","password":"Sandbox#Check2026!qz"}'
    Say "[OK]   로그인: $($login.display_name) / $($login.role_code) / 비밀번호변경필요=$($login.must_change_password)"
    $csrf = ($s.Cookies.GetCookies('http://127.0.0.1:8080') | Where-Object { $_.Name -eq 'soc_csrf' }).Value
    $headers = @{ 'X-CSRF-Token' = $csrf }
    $companies = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/companies' -WebSession $s
    $body = @{ company_id = $companies[0].id; title = '샌드박스 점검'; content = '깨끗한 PC 설치 확인'
               status_code = 'NEW' } | ConvertTo-Json
    $made = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/handovers' -Method Post -WebSession $s `
        -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
    Say "[OK]   인수인계 등록 #$($made.id) / 제목 '$($made.title)'"
} catch { Say "[FAIL] 로그인 · 등록: $($_.Exception.Message)" }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\SOC-Handover\backup.ps1' *>&1 |
    ForEach-Object { Add-Content -Path $log -Value "  backup| $_" -Encoding UTF8 }
Check '백업 파일 생성' { (Get-ChildItem 'C:\SOC-Handover\backup' -Filter '*.dump' -ErrorAction SilentlyContinue).Count }

Say '===== 중지 · 시작 ====='
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\SOC-Handover\stop.ps1' *>&1 |
    ForEach-Object { Add-Content -Path $log -Value "  stop| $_" -Encoding UTF8 }
Start-Sleep -Seconds 3
Check '중지 후 응답 없음' { -not (Test-NetConnection 127.0.0.1 -Port 8080 -InformationLevel Quiet -WarningAction SilentlyContinue) }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\SOC-Handover\start.ps1' *>&1 |
    ForEach-Object { Add-Content -Path $log -Value "  start| $_" -Encoding UTF8 }
$again = $null
for ($i = 0; $i -lt 30; $i++) {
    try { $again = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 3 } catch { }
    if ($again) { break }
    Start-Sleep -Seconds 2
}
Say "다시 시작 후 health: $($again | ConvertTo-Json -Compress)"

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\SOC-Handover\status.ps1' *>&1 |
    ForEach-Object { Add-Content -Path $log -Value "  status| $_" -Encoding UTF8 }

Copy-Item 'C:\SOC-Handover\logs\*.log' $result -ErrorAction SilentlyContinue
Copy-Item 'C:\SOC-Handover\data\pgdata\log\*' $result -ErrorAction SilentlyContinue
Say '===== 끝 ====='
Set-Content -Path (Join-Path $result 'DONE.txt') -Value (Get-Date -Format s) -Encoding ASCII
Write-Host ''
Write-Host '검증이 끝났습니다. 이 창을 닫고 샌드박스를 종료하셔도 됩니다.' -ForegroundColor Green
Write-Host "결과: $result (공유 폴더에 그대로 남습니다)" -ForegroundColor Green
