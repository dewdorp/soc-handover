<#
.SYNOPSIS
    인터넷 없는 PC 용 오프라인 설치 패키지(zip) 만들기 — 개발 PC(인터넷 되는 곳)에서 실행

.DESCRIPTION
    필요한 것을 모두 담은 zip 하나를 만듭니다. 대상 PC 에는 아무것도 미리 설치할 필요가 없습니다.

      SOC-Handover-<버전>\
        INSTALL.cmd              더블클릭 → 관리자 권한 요청 → 설치/업그레이드
        README-KO.txt            설치 안내
        setup\setup.ps1          설치 프로그램 본체
        setup\vc_redist.x64.exe  Visual C++ 런타임(PostgreSQL 에 필요, 없을 때만 설치)
        payload\                 설치 폴더(C:\SOC-Handover)로 복사되는 것
          backend\ frontend\dist\ scripts\ docs\ *.ps1 *.cmd
          runtime\python\        Python 3.12 + 서버 라이브러리(설치 완료 상태)
          runtime\pgsql\         PostgreSQL 16 (bin · lib · share 만)
          runtime\wheels\        라이브러리 원본(현장 복구용)
        MANIFEST.sha256          파일마다 해시 — 설치 프로그램이 복사 손상을 검사
        VERSION.txt

    외부 배포 파일은 build\cache 에 둡니다(없으면 -Download 로 받음, git 에는 올리지 않음).
      postgresql-16.x-windows-x64-binaries.zip  (EnterpriseDB 공식)
      vc_redist.x64.exe                         (Microsoft 공식)
      wheels\                                   (PyPI — requirements.lock 버전 그대로)

.PARAMETER Download
    build\cache 에 없는 외부 배포 파일을 인터넷에서 받습니다.

.PARAMETER SkipFrontendBuild
    화면을 다시 빌드하지 않고 지금의 frontend\dist 를 씁니다.

.PARAMETER AppOnly
    이미 설치된 PC 용 **패치 zip**(수 MB)만 만듭니다. 앱 · 화면 · 스크립트 · 문서만 담고
    Python · PostgreSQL 은 담지 않습니다(설치된 것을 그대로 씁니다).

      SOC-Handover-<버전>-patch\
        UPDATE.cmd               더블클릭 → 중지 · 백업 · 교체 · 마이그레이션 · 시작
        setup\update.ps1         패치 프로그램 본체
        patch\                   설치 폴더에 덮어쓰는 것(backend · frontend\dist · scripts · docs · *.ps1 *.cmd)
        MANIFEST.sha256 · VERSION.txt · README-PATCH.txt

    라이브러리(requirements.lock)가 바뀐 버전에는 쓸 수 없습니다 — 패치 프로그램이 확인하고
    전체 패키지로 안내합니다.

.PARAMETER OutDir
    zip 을 만들 폴더. 기본 build\dist.

.EXAMPLE
    .\package.ps1 -Download
    .\package.ps1 -AppOnly
#>
[CmdletBinding()]
param(
    [switch]$Download,
    [switch]$SkipFrontendBuild,
    [switch]$AppOnly,
    [string]$OutDir
)

. "$PSScriptRoot\scripts\common.ps1"

$PgVersion = '16.15-2'
$PgUrl = "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip"
$VcUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'

$BuildDir = Join-Path $Root 'build'
$Cache = Join-Path $BuildDir 'cache'
$PgZip = Join-Path $Cache "postgresql-$PgVersion-windows-x64-binaries.zip"
$VcExe = Join-Path $Cache 'vc_redist.x64.exe'
$Wheels = Join-Path $Cache 'wheels'
if (-not $OutDir) { $OutDir = Join-Path $BuildDir 'dist' }

$initPy = Get-Content (Join-Path $BackendDir 'app\__init__.py') -Raw
if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') { Write-Err 'app\__init__.py 에서 버전을 읽지 못했습니다.'; exit 1 }
$Version = $Matches[1]
$Name = "SOC-Handover-$Version"
$Stage = Join-Path $BuildDir "stage\$Name"
$PayloadDir = Join-Path $Stage 'payload'

function Invoke-Robo([string]$From, [string]$To, [string[]]$Extra) {
    $null = & robocopy.exe $From $To @Extra /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw "복사 실패: $From → $To (robocopy $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

# 설치 폴더에 들어가는 '앱' — 전체 패키지와 패치가 똑같은 것을 담도록 한 곳에서 만든다.
# 런타임(Python · PostgreSQL)은 여기 없다: 전체 패키지만 담고, 패치는 설치된 것을 그대로 쓴다.
function Copy-AppFiles([string]$Dest) {
    Invoke-Robo (Join-Path $BackendDir 'app') (Join-Path $Dest 'backend\app') @('/E', '/XD', '__pycache__')
    Invoke-Robo (Join-Path $BackendDir 'alembic') (Join-Path $Dest 'backend\alembic') @('/E', '/XD', '__pycache__')
    foreach ($f in @('alembic.ini', 'manage.py', 'requirements.txt', 'requirements.lock')) {
        Copy-Item (Join-Path $BackendDir $f) (Join-Path $Dest "backend\$f")
    }
    Invoke-Robo (Join-Path $FrontendDir 'dist') (Join-Path $Dest 'frontend\dist') @('/E')
    New-Item -ItemType Directory -Path (Join-Path $Dest 'scripts') -Force | Out-Null
    # verify_install.py 는 설치 PC 에서 돌리는 점검이다(읽기만 한다). demo_seed · screenshots 는
    # 개발 PC 전용이라 넣지 않는다 — 운영 DB 에 시연 자료를 넣는 사고를 만들지 않는다.
    foreach ($f in @('common.ps1', 'service-run.ps1', 'verify_install.py')) { Copy-Item (Join-Path $Root "scripts\$f") (Join-Path $Dest "scripts\$f") }
    foreach ($f in @('start.ps1', 'stop.ps1', 'status.ps1', 'backup.ps1', 'restore.ps1')) { Copy-Item (Join-Path $Root $f) $Dest }
    Copy-Item (Join-Path $Root 'deploy\uninstall.ps1') $Dest
    New-Item -ItemType Directory -Path (Join-Path $Dest 'docs') -Force | Out-Null
    Copy-Item (Join-Path $Root 'docs\OPERATIONS.md') (Join-Path $Dest 'docs\OPERATIONS.md')
    Copy-Item (Join-Path $Root 'deploy\README-KO.txt') (Join-Path $Dest 'README-KO.txt')

    # 설치 폴더의 실행 파일(.cmd) — 서비스 모드면 관리자 권한을 요청한다(status 는 권한 없이)
    $cmdTemplate = @'
@echo off
rem SOC Handover - {0}. See docs\OPERATIONS.md
setlocal
cd /d "%~dp0"
if {1}=="elevate" if exist "%~dp0SERVICE_MODE" (
  fltmc >nul 2>&1
  if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0{0}.ps1" %*
echo.
pause
'@
    foreach ($op in @('start', 'stop', 'status', 'backup', 'restore', 'uninstall')) {
        $mode = if ($op -eq 'status') { 'no' } else { 'elevate' }
        $text = [string]::Format($cmdTemplate, $op, $mode)
        [IO.File]::WriteAllText((Join-Path $Dest "$op.cmd"), $text, [Text.Encoding]::ASCII)
    }
}

Write-Host '=====================================================' -ForegroundColor White
Write-Host $(if ($AppOnly) { " 패치 패키지 만들기 — $Name" } else { " 오프라인 설치 패키지 만들기 — $Name" }) -ForegroundColor White
Write-Host '=====================================================' -ForegroundColor White

# ---------------------------------------------------------------- 패치(앱만) 패키지
if ($AppOnly) {
    try {
        if (-not $SkipFrontendBuild) {
            Write-Step '화면(UI) 빌드'
            $pm = Resolve-PackageManager
            if (-not $pm) { throw 'Node/pnpm 을 찾지 못했습니다. -SkipFrontendBuild 로 지금의 dist 를 쓰거나 Node 를 설치하십시오.' }
            Invoke-PackageManager $pm @('run', 'build') $FrontendDir
            Write-Ok 'frontend\dist 빌드'
        }
        if (-not (Test-Path (Join-Path $FrontendDir 'dist\index.html'))) { throw 'frontend\dist 가 없습니다.' }

        Write-Step '패치 구성'
        $patchStage = Join-Path $BuildDir "stage\$Name-patch"
        if (Test-Path $patchStage) { Remove-Item $patchStage -Recurse -Force }
        $patchDir = Join-Path $patchStage 'patch'
        New-Item -ItemType Directory -Path $patchDir -Force | Out-Null
        Copy-AppFiles $patchDir
        Write-Ok '앱 · 화면 · 운영 스크립트'

        New-Item -ItemType Directory -Path (Join-Path $patchStage 'setup') -Force | Out-Null
        Copy-Item (Join-Path $Root 'deploy\update.ps1') (Join-Path $patchStage 'setup\update.ps1')
        Copy-Item (Join-Path $Root 'deploy\UPDATE.cmd') (Join-Path $patchStage 'UPDATE.cmd')
        Copy-Item (Join-Path $Root 'deploy\README-PATCH.txt') (Join-Path $patchStage 'README-PATCH.txt')
        Set-Content -Path (Join-Path $patchStage 'VERSION.txt') -Encoding ASCII -Value @(
            $Version, "built $(Get-Date -Format 'yyyy-MM-dd HH:mm')", 'patch (app only)')
        Write-Ok '패치 프로그램 · 안내문'

        Write-Step '인코딩 정리 · 무결성 목록 · 압축'
        $helper = Join-Path $Root 'deploy\pack_helper.py'
        & $VenvPython $helper normalize $patchStage
        if ($LASTEXITCODE -ne 0) { throw '인코딩 정리 실패' }
        & $VenvPython $helper manifest $patchStage
        if ($LASTEXITCODE -ne 0) { throw '무결성 목록 생성 실패' }
        $patchZip = Join-Path $OutDir "$Name-patch.zip"
        & $VenvPython $helper zip $patchStage $patchZip
        if ($LASTEXITCODE -ne 0) { throw '압축 실패' }

        Write-Host ''
        Write-Host '=====================================================' -ForegroundColor Green
        Write-Host ' 패치 패키지 생성 완료' -ForegroundColor Green
        Write-Host '=====================================================' -ForegroundColor Green
        Write-Host "  파일   : $patchZip ($([math]::Round((Get-Item $patchZip).Length / 1MB, 1))MB)"
        Write-Host "  해시   : $patchZip.sha256"
        Write-Host '  옮긴 뒤: 압축을 풀고 UPDATE.cmd 더블클릭 (README-PATCH.txt 참고)'
        Write-Host '  주의   : 라이브러리(requirements.lock)가 바뀐 버전에는 쓸 수 없습니다 — 패치 프로그램이 확인합니다.'
        Write-Host ''
        exit 0
    } catch {
        Write-Err $_.Exception.Message
        exit 1
    }
}

try {
    # ------------------------------------------------------------ 1. 외부 배포 파일
    Write-Step '외부 배포 파일 (build\cache)'
    New-Item -ItemType Directory -Path $Cache -Force | Out-Null
    foreach ($item in @(@{ Path = $PgZip; Url = $PgUrl; Name = "PostgreSQL $PgVersion" },
                        @{ Path = $VcExe; Url = $VcUrl; Name = 'Visual C++ 재배포 패키지' })) {
        if (-not (Test-Path $item.Path)) {
            if (-not $Download) { throw "$($item.Name) 가 없습니다: $($item.Path)  (-Download 로 받으십시오)" }
            Write-Host "    내려받는 중: $($item.Url)"
            & curl.exe -sSL --fail -o $item.Path $item.Url
            if ($LASTEXITCODE -ne 0) { Remove-Item $item.Path -ErrorAction SilentlyContinue; throw "$($item.Name) 내려받기 실패" }
        }
        Write-Ok "$($item.Name): $([math]::Round((Get-Item $item.Path).Length / 1MB, 1))MB"
    }

    $lock = Join-Path $BackendDir 'requirements.lock'
    $haveWheels = (Test-Path $Wheels) -and (Get-ChildItem $Wheels -Filter *.whl -ErrorAction SilentlyContinue)
    if (-not $haveWheels) {
        if (-not $Download) { throw "Python 라이브러리(wheel)가 없습니다: $Wheels  (-Download 로 받으십시오)" }
        New-Item -ItemType Directory -Path $Wheels -Force | Out-Null
        & $VenvPython -m pip download --disable-pip-version-check -q --only-binary=:all: --platform win_amd64 `
            --python-version 3.12 --implementation cp -r (Join-Path $BackendDir 'requirements.txt') -c $lock -d $Wheels
        if ($LASTEXITCODE -ne 0) { throw 'wheel 내려받기 실패' }
    }
    Write-Ok "Python 라이브러리: $((Get-ChildItem $Wheels -Filter *.whl).Count)개 (requirements.lock 버전)"

    # ------------------------------------------------------------ 2. 화면 빌드
    if (-not $SkipFrontendBuild) {
        Write-Step '화면(UI) 빌드'
        $pm = Resolve-PackageManager
        if (-not $pm) { throw 'Node/pnpm 을 찾지 못했습니다. -SkipFrontendBuild 로 지금의 dist 를 쓰거나 Node 를 설치하십시오.' }
        Invoke-PackageManager $pm @('run', 'build') $FrontendDir
        Write-Ok 'frontend\dist 빌드'
    }
    if (-not (Test-Path (Join-Path $FrontendDir 'dist\index.html'))) { throw 'frontend\dist 가 없습니다.' }

    # ------------------------------------------------------------ 3. 준비 폴더
    Write-Step '패키지 구성'
    if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
    New-Item -ItemType Directory -Path $PayloadDir -Force | Out-Null

    Copy-AppFiles $PayloadDir
    Write-Ok '앱 · 화면 · 운영 스크립트'

    # Python 런타임: 이 PC 의 Python 3.12(개발 venv 의 원본)를 복사하고, 라이브러리를 그 안에 설치한다
    Write-Step 'Python 런타임'
    $cfg = Get-Content (Join-Path $BackendDir '.venv\pyvenv.cfg')
    $pyHome = (($cfg | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', '').Trim()
    $pyExe = Join-Path $pyHome 'python.exe'
    $pyVer = & $pyExe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    if ($pyVer -notlike '3.12.*') { throw "Python 3.12 가 필요합니다(지금 $pyVer, $pyHome)" }
    $rtDir = Join-Path $PayloadDir 'runtime\python'
    Invoke-Robo $pyHome $rtDir @('/E', '/XD', 'Doc', 'tcl', 'include', 'libs', 'Scripts', 'Tools', 'test', 'tests', 'idlelib',
        'tkinter', 'turtledemo', 'site-packages', '__pycache__',
        '/XF', '*.pdb', '_tkinter.pyd', 'tcl86t.dll', 'tk86t.dll', '*_d.pyd', '*_d.dll', 'python_d.exe', 'pythonw_d.exe')
    $rtPy = Join-Path $rtDir 'python.exe'
    New-Item -ItemType Directory -Path (Join-Path $rtDir 'Lib\site-packages') -Force | Out-Null
    $env:PIP_NO_WARN_SCRIPT_LOCATION = '1'
    & $rtPy -m ensurepip --default-pip | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'ensurepip 실패' }
    & $rtPy -m pip install --disable-pip-version-check -q --no-warn-script-location --no-index `
        --find-links $Wheels -r (Join-Path $BackendDir 'requirements.txt') -c $lock
    if ($LASTEXITCODE -ne 0) { throw '라이브러리 설치 실패' }
    Remove-Item (Join-Path $rtDir 'Scripts') -Recurse -Force -ErrorAction SilentlyContinue   # 절대경로가 박힌 실행 파일
    & $rtPy -c "import fastapi, uvicorn, sqlalchemy, alembic, psycopg, argon2, openpyxl, xlsxwriter, apscheduler, dateutil, multipart; print('ok', psycopg.pq.version())"
    if ($LASTEXITCODE -ne 0) { throw '라이브러리 import 확인 실패' }
    # 미리 컴파일 — 첫 기동이 빨라지고, 쓰기 권한이 없는 폴더에서도 .pyc 를 만들려다 실패하지 않는다
    & $rtPy -m compileall -q -j 0 (Join-Path $rtDir 'Lib') (Join-Path $PayloadDir 'backend') | Out-Null
    $global:LASTEXITCODE = 0   # 일부 표준 라이브러리 예제 파일은 일부러 문법 오류라 컴파일 경고가 난다(무시)
    Write-Ok "Python $pyVer + 라이브러리 $((& $rtPy -m pip list --disable-pip-version-check --format=freeze).Count)개"

    # PostgreSQL: 서버 실행에 필요한 bin · lib · share 만(pgAdmin · 문서 · StackBuilder 제외)
    Write-Step 'PostgreSQL'
    $pgOut = Join-Path $PayloadDir 'runtime\pgsql'
    & $VenvPython -c @"
import zipfile, os, shutil, sys
src, out = sys.argv[1], sys.argv[2]
keep_dirs = ('pgsql/bin/', 'pgsql/lib/', 'pgsql/share/')
keep_files = {'pgsql/server_license.txt', 'pgsql/commandlinetools_3rd_party_licenses.txt'}
skip_bin = {'stackbuilder.exe', 'isolationtester.exe', 'libpq_pipeline.exe', 'libpq_testclient.exe',
            'libpq_uri_regress.exe', 'pg_isolation_regress.exe', 'pg_regress.exe', 'pg_regress_ecpg.exe',
            'test_cloexec.exe', 'testplug.dll'}
# 쓰지 않는 절차 언어 모듈 — 우리가 넣지 않는 Perl · Tcl · Python 3.11 런타임을 요구한다.
# 남겨 두면 누군가 CREATE EXTENSION 할 때 '왜 안 되는지' 헷갈리므로 아예 뺀다(우리는 plpgsql · pg_trgm 만 쓴다).
skip_lib = {'plperl.dll', 'bool_plperl.dll', 'hstore_plperl.dll', 'jsonb_plperl.dll',
            'plpython3.dll', 'hstore_plpython3.dll', 'jsonb_plpython3.dll', 'ltree_plpython3.dll',
            'pltcl.dll'}
n = 0
with zipfile.ZipFile(src) as z:
    for i in z.infolist():
        name = i.filename
        if i.is_dir() or not (name.startswith(keep_dirs) or name in keep_files):
            continue
        base = name.split('/')[-1].lower()
        if name.startswith('pgsql/bin/') and (base in skip_bin or base.startswith(('wxbase', 'wxmsw'))):
            continue
        if name.startswith('pgsql/lib/') and (base.endswith('.lib') or base in skip_lib):
            continue
        dest = os.path.join(out, *name.split('/')[1:])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(i) as r, open(dest, 'wb') as w:
            shutil.copyfileobj(r, w)
        n += 1
print(n)
"@ $PgZip $pgOut
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 압축 풀기 실패' }
    $pgVer = & (Join-Path $pgOut 'bin\postgres.exe') --version
    Write-Ok "$pgVer"

    Invoke-Robo $Wheels (Join-Path $PayloadDir 'runtime\wheels') @('*.whl')
    Write-Ok '라이브러리 원본(runtime\wheels) — 현장 복구용'

    # 설치 프로그램
    New-Item -ItemType Directory -Path (Join-Path $Stage 'setup') -Force | Out-Null
    Copy-Item (Join-Path $Root 'deploy\setup.ps1') (Join-Path $Stage 'setup\setup.ps1')
    Copy-Item $VcExe (Join-Path $Stage 'setup\vc_redist.x64.exe')
    Copy-Item (Join-Path $Root 'deploy\INSTALL.cmd') (Join-Path $Stage 'INSTALL.cmd')
    Copy-Item (Join-Path $Root 'deploy\README-KO.txt') (Join-Path $Stage 'README-KO.txt')
    # VERSION.txt 는 payload 에 넣지 않는다 — 설치 프로그램이 끝까지 성공했을 때만 설치 폴더에 써서
    # '설치 완료(다음 실행은 업그레이드)' 표시로 쓴다.
    Set-Content -Path (Join-Path $Stage 'VERSION.txt') -Encoding ASCII -Value @(
        $Version, "built $(Get-Date -Format 'yyyy-MM-dd HH:mm')", "python $pyVer", "$pgVer")

    # ------------------------------------------------------------ 4. 마무리 · 압축
    Write-Step 'Windows 10 호환성 검사'
    & $VenvPython (Join-Path $Root 'deploy\audit_pe.py') $Stage
    if ($LASTEXITCODE -ne 0) { throw 'Windows 10 에서 실행할 수 없는 파일이 있습니다(위 목록 참고).' }

    Write-Step '인코딩 정리 · 무결성 목록 · 압축'
    $helper = Join-Path $Root 'deploy\pack_helper.py'
    & $VenvPython $helper normalize $Stage
    if ($LASTEXITCODE -ne 0) { throw '인코딩 정리 실패' }
    & $VenvPython $helper manifest $Stage
    if ($LASTEXITCODE -ne 0) { throw '무결성 목록 생성 실패' }
    $zip = Join-Path $OutDir "$Name-offline.zip"
    & $VenvPython $helper zip $Stage $zip
    if ($LASTEXITCODE -ne 0) { throw '압축 실패' }

    $stageMb = [math]::Round(((Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 0)
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host ' 패키지 생성 완료' -ForegroundColor Green
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host "  파일   : $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1))MB, 풀면 ${stageMb}MB)"
    Write-Host "  해시   : $zip.sha256"
    Write-Host '  옮긴 뒤: 압축을 풀고 INSTALL.cmd 더블클릭 (README-KO.txt 참고)'
    Write-Host ''
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
