<#
.SYNOPSIS
    SOC 인수인계 플랫폼 설치 (Windows 10/11)

.DESCRIPTION
    전제조건 확인 → .env 생성 → Python 가상환경/의존성 → DB 마이그레이션 →
    기준 데이터 → 관리자 계정 → 프론트엔드 빌드 순으로 수행합니다.
    여러 번 실행해도 안전합니다(이미 된 단계는 건너뜁니다).

.PARAMETER SkipFrontend
    프론트엔드 설치/빌드를 건너뜁니다(백엔드만 갱신할 때).

.PARAMETER Force
    .env 가 이미 있어도 다시 만듭니다(SECRET_KEY 재생성 — 기존 세션은 모두 끊깁니다).

.EXAMPLE
    .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$Force
)

. "$PSScriptRoot\scripts\common.ps1"

Write-Host "==============================================" -ForegroundColor White
Write-Host " SOC 교대근무 인수인계 플랫폼 설치" -ForegroundColor White
Write-Host "==============================================" -ForegroundColor White

Ensure-Dirs

# ---------------------------------------------------------------- 1. 전제조건
Write-Step '전제조건 확인'

$python = Resolve-PythonExe
if (-not $python) {
    Write-Err 'Python 3.12 를 찾지 못했습니다.'
    Write-Host '   https://www.python.org/downloads/ 에서 설치하거나,'
    Write-Host '   .env 에 PYTHON_EXE=C:\경로\python.exe 를 지정하십시오.'
    exit 1
}
$pyVersion = (& $python --version 2>&1)
Write-Ok "Python: $pyVersion ($python)"

$dbIsPostgres = $false
$pgBin = $null
foreach ($p in @('C:\Program Files\PostgreSQL\17\bin', 'C:\Program Files\PostgreSQL\16\bin',
                 'C:\Program Files\PostgreSQL\15\bin')) {
    if (Test-Path (Join-Path $p 'psql.exe')) { $pgBin = $p; break }
}
if (-not $pgBin) {
    $psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($psqlCmd) { $pgBin = Split-Path -Parent $psqlCmd.Source }
}
if ($pgBin) {
    Write-Ok "PostgreSQL 도구: $pgBin"
    $dbIsPostgres = $true
} else {
    Write-Warn2 'PostgreSQL 이 설치되어 있지 않습니다.'
    Write-Host '    → 개발/평가용 SQLite 로 진행합니다. 운영에는 PostgreSQL 을 설치하십시오.'
    Write-Host '      (설치 후 .env 의 DATABASE_URL 을 수정하고 install.ps1 을 다시 실행)'
}

$prebuiltUi = Test-Path (Join-Path $FrontendDir 'dist\index.html')

if (-not $SkipFrontend) {
    $node = Resolve-NodeExe
    if ($node) {
        Write-Ok "Node.js: $(& $node --version) ($node)"
    } elseif ($prebuiltUi) {
        # 이전 패키지(package.ps1 -Offline)에 빌드 결과가 포함된 경우
        Write-Ok '사전 빌드된 UI 사용 (Node.js 불필요)'
        $SkipFrontend = $true
    } else {
        Write-Warn2 'Node.js 를 찾지 못해 프론트엔드 빌드를 건너뜁니다. (API 만 동작)'
        $SkipFrontend = $true
    }
}

$wheelDir = Join-Path $BackendDir 'offline-wheels'
$offlineWheels = Test-Path $wheelDir
if ($offlineWheels) {
    Write-Ok "오프라인 패키지 감지: $((Get-ChildItem $wheelDir -File).Count)개 wheel (인터넷 불필요)"
}

# ---------------------------------------------------------------- 2. .env
Write-Step '.env 구성'

if ((Test-Path $EnvFile) -and -not $Force) {
    Write-Ok '.env 가 이미 있습니다(유지).'
} else {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('/', '_').Replace('+', '-')

    $dbUrl = if ($dbIsPostgres) {
        'postgresql+psycopg://soc_app:CHANGE_ME@127.0.0.1:5432/soc_handover'
    } else {
        "sqlite+pysqlite:///$((Join-Path $DataDir 'soc_handover.db') -replace '\\','/')"
    }

    @(
        '# SOC Handover Platform - 환경설정',
        '# 이 파일에는 비밀값이 들어갑니다. 공유하지 마십시오.',
        '',
        'APP_ENV=prod',
        'APP_HOST=0.0.0.0',
        'APP_PORT=8080',
        'ENABLE_DOCS=false',
        '',
        "SECRET_KEY=$secret",
        'ACCESS_TOKEN_MINUTES=15',
        'REFRESH_TOKEN_HOURS=12',
        'COOKIE_SECURE=false',
        '',
        "DATABASE_URL=$dbUrl",
        '',
        '# AI 는 기본 비활성. 사용하려면 ollama 또는 openai_compatible 로 변경하십시오.',
        'LLM_PROVIDER=disabled',
        'LLM_BASE_URL=',
        'LLM_API_KEY=',
        'LLM_MODEL=',
        '',
        '# 런타임 경로를 직접 지정할 때만 사용',
        '# PYTHON_EXE=',
        '# NODE_EXE='
    ) | Set-Content -Path $EnvFile -Encoding UTF8
    Write-Ok ".env 생성 완료 (SECRET_KEY 자동 생성)"
    if ($dbIsPostgres) {
        Write-Warn2 'DATABASE_URL 의 사용자/비밀번호를 실제 값으로 수정한 뒤 다시 실행하십시오.'
    }
}

Import-DotEnv | Out-Null

# ---------------------------------------------------------------- 3. 백엔드
Write-Step 'Python 가상환경 및 의존성'

if (-not (Test-Path $VenvPython)) {
    & $python -m venv (Join-Path $BackendDir '.venv')
    if ($LASTEXITCODE -ne 0) { Write-Err '가상환경 생성 실패'; exit 1 }
    Write-Ok '가상환경 생성'
} else {
    Write-Ok '가상환경 존재(재사용)'
}

if ($offlineWheels) {
    & $VenvPython -m pip install --disable-pip-version-check -q --no-index `
        --find-links $wheelDir -r (Join-Path $BackendDir 'requirements.txt')
} else {
    & $VenvPython -m pip install --disable-pip-version-check -q --upgrade pip
    & $VenvPython -m pip install --disable-pip-version-check -q `
        -r (Join-Path $BackendDir 'requirements.txt')
}
if ($LASTEXITCODE -ne 0) {
    Write-Err '의존성 설치 실패'
    if (-not $offlineWheels) {
        Write-Host '   인터넷이 차단된 환경이면 인터넷 되는 PC에서 .\package.ps1 -Offline 으로'
        Write-Host '   패키지를 만들어 옮기십시오.'
    }
    exit 1
}
Write-Ok "백엔드 의존성 설치 완료$(if ($offlineWheels) { ' (오프라인)' })"

# ---------------------------------------------------------------- 4. DB
Write-Step '데이터베이스 마이그레이션'

Push-Location $BackendDir
try {
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Err '마이그레이션 실패. DATABASE_URL 과 DB 서버 상태를 확인하십시오.'
        exit 1
    }
    Write-Ok '스키마 최신화 완료'

    & $VenvPython manage.py bootstrap
    if ($LASTEXITCODE -ne 0) { Write-Err '기준 데이터 구성 실패'; exit 1 }
} finally { Pop-Location }

# ---------------------------------------------------------------- 5. 관리자
Write-Step '관리자 계정'

Push-Location $BackendDir
try {
    $hasAdmin = & $VenvPython -c @"
from app.core.db import SessionLocal
from app.models.user import User
from sqlalchemy import select
with SessionLocal() as db:
    print('YES' if db.scalar(select(User).where(User.role_code=='ADMIN')) else 'NO')
"@
    if ($hasAdmin -match 'YES') {
        Write-Ok '관리자 계정이 이미 있습니다(유지).'
    } else {
        Write-Host '  관리자 비밀번호를 입력하십시오. (12자 이상, 영문 대/소문자·숫자·특수문자 중 3종)'
        Write-Host '  입력값은 화면에 표시되지 않으며, 해시만 저장됩니다.'
        & $VenvPython manage.py create-admin --username admin --display-name "시스템 관리자"
        if ($LASTEXITCODE -ne 0) { Write-Err '관리자 계정 생성 실패'; exit 1 }
    }
} finally { Pop-Location }

# ---------------------------------------------------------------- 6. 프론트엔드
if (-not $SkipFrontend) {
    Write-Step '프론트엔드 설치 및 빌드'
    $pm = Resolve-PackageManager
    if (-not $pm) {
        Write-Warn2 'npm/pnpm 을 찾지 못했습니다. 프론트엔드 빌드를 건너뜁니다.'
    } else {
        Write-Ok "패키지 매니저: $($pm.Kind)"
        Invoke-PackageManager $pm @('install') $FrontendDir
        Invoke-PackageManager $pm @('run', 'build') $FrontendDir
        Write-Ok '프론트엔드 빌드 완료 (frontend\dist)'
    }
}

# ---------------------------------------------------------------- 완료
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' 설치 완료' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ''
Write-Host '  실행     : .\start.ps1'
Write-Host '  상태     : .\status.ps1'
Write-Host '  중지     : .\stop.ps1'
Write-Host '  백업     : .\backup.ps1'
Write-Host ''
if (-not $dbIsPostgres) {
    Write-Warn2 '현재 개발/평가용 SQLite 로 구성되어 있습니다. 운영 전에 PostgreSQL 로 전환하십시오.'
}
