"""E2E 준비 — 측정용 DB 에 실제 서버(uvicorn)를 띄우고 Edge 로 화면을 조작한다.

    set E2E_DATABASE_URL=postgresql+psycopg://soc_e2e:...@127.0.0.1:55440/soc_e2e
    python -m pytest tests/e2e -q            (없으면 임시 SQLite 파일로 돈다)

- 스키마는 실제 마이그레이션으로 만든다(운영과 같은 경로).
- 브라우저는 이 PC 에 설치된 Microsoft Edge 를 쓴다(따로 내려받지 않음).
- 계정: admin(관리자) · e2e_day(근무자) · e2e_night(근무자) — 교대 인계 시나리오용.
"""
from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2]
ADMIN_PW = "E2E#Owner2026!zq"
USER_PW = "E2E#Shift2026!zq"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """빈 DB + 실행 중인 서버. 끝나면 정리한다."""
    data_dir = tmp_path_factory.mktemp("e2e-data")
    port = _free_port()
    url = os.environ.get("E2E_DATABASE_URL") or f"sqlite+pysqlite:///{(data_dir / 'e2e.db').as_posix()}"
    env = {
        **os.environ,
        "APP_ENV": "prod", "APP_HOST": "127.0.0.1", "APP_PORT": str(port),
        "DATABASE_URL": url,
        "SECRET_KEY": "e2e-only-secret-key-0123456789-0123456789",
        # 운영과 같게 APP_ENV=prod 로 띄우므로 비밀번호 보관 키도 운영처럼 명시해 준다
        # (키가 없으면 그 기능만 꺼진 채로 뜬다 — 그것도 의도한 동작이다)
        "VAULT_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "DATA_DIR": str(data_dir / "data"), "BACKUP_DIR": str(data_dir / "backup"),
        "LOG_DIR": str(data_dir / "logs"), "COOKIE_SECURE": "false",
        "REMINDER_INTERVAL_MIN": "0", "ENABLE_DOCS": "false",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "SOC_ADMIN_PASSWORD": ADMIN_PW,
    }
    py = sys.executable

    if url.startswith("postgres"):
        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()

    run = lambda args: subprocess.run(args, cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8")
    for args in ([py, "-m", "alembic", "upgrade", "head"],
                 [py, "manage.py", "bootstrap"],
                 [py, "manage.py", "create-admin", "--username", "admin",
                  "--display-name", "시스템 관리자", "--no-force-change"]):
        r = run(args)
        assert r.returncode == 0, f"{args[1:]} 실패: {r.stderr[-2000:]}"

    logs = open(data_dir / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=logs, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(f"{base}/api/v1/health", timeout=2).status_code == 200:
                break
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"서버가 죽었습니다:\n{(data_dir / 'server.log').read_text(encoding='utf-8')[-3000:]}")
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("서버가 60초 안에 뜨지 않았습니다.")

    # 시나리오용 계정 · 관계사
    with httpx.Client(base_url=f"{base}/api/v1", timeout=20) as c:
        c.post("/auth/login", json={"username": "admin", "password": ADMIN_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        for username, name in (("e2e_day", "주간근무자"), ("e2e_night", "야간근무자")):
            c.post("/users", json={"username": username, "display_name": name, "password": USER_PW,
                                   "role_code": "ANALYST", "must_change_password": False})
        companies = c.get("/companies").json()
        if not companies:
            companies = [c.post("/companies", json={"name": "A보안"}).json()]

    yield {"base": base, "company": companies[0]["name"]}

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    logs.close()
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """이 PC 에 설치된 Edge 를 쓴다(브라우저를 따로 내려받지 않게)."""
    return {**browser_type_launch_args, "channel": os.environ.get("E2E_BROWSER_CHANNEL", "msedge")}


@pytest.fixture
def login(page, server):
    """화면으로 실제 로그인한다(API 로 쿠키를 심지 않는다 — 로그인 화면도 시나리오의 일부)."""
    def _login(username: str = "admin", password: str = ADMIN_PW):
        # 앞선 로그인이 남아 있으면 /login 이 대시보드로 되돌려진다 — 쿠키부터 비우고 시작한다
        page.context.clear_cookies()
        page.goto(server["base"] + "/login")
        page.get_by_label("계정").fill(username)
        page.get_by_label("비밀번호").fill(password)
        page.get_by_role("button", name="로그인").click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        return page
    return _login
