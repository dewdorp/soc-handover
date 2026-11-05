"""테스트 공통 설정.

실제 DB 와 실제 API 를 사용한다. In-memory mock 으로 대체하지 않는다(§88).

- 기본: 임시 SQLite 파일. 스키마는 모델에서 바로 만든다.
- `TEST_DATABASE_URL` 을 주면 그 PostgreSQL 에서 돈다(운영 DB 와 같은 방언). 스키마는 **실제 마이그레이션**
  (alembic upgrade head)으로 만들어 PG 전용 객체(tsvector 트리거 · trigram 인덱스)까지 함께 검증한다.
  그 DB 의 public 스키마는 통째로 지우고 다시 만드므로 **테스트 전용 DB** 만 주어야 한다.
    예) TEST_DATABASE_URL=postgresql+psycopg://soc_test:soctest@127.0.0.1:55440/soc_test
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# --- 앱 import 이전에 환경을 고정한다 ---
_TMP = Path(tempfile.mkdtemp(prefix="soc_handover_test_"))
os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production-use-0123456789"
_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = _PG_URL or f"sqlite+pysqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["BACKUP_DIR"] = str(_TMP / "backup")
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.middleware import limiter  # noqa: E402
from app.core.security import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import bootstrap_service  # noqa: E402

ADMIN_PW = "AdminTest!2026#soc"
MANAGER_PW = "ManagerTest!2026#soc"
ANALYST_PW = "AnalystTest!2026#soc"


def _migrate_postgres() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if _PG_URL:
        _migrate_postgres()
    else:
        Base.metadata.create_all(engine)
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db(_schema):
    """테스트마다 데이터를 비우고 기준 데이터를 다시 구성한다."""
    with SessionLocal() as db:
        if _PG_URL:
            # 한 번에 비우고 번호도 1부터 — 테스트가 id 를 가정해도 SQLite 와 같게
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
        db.commit()
        bootstrap_service.ensure_reference_data(db)
        bootstrap_service.ensure_default_company(db)
        db.commit()
    limiter.reset()
    yield


@pytest.fixture
def db() -> Session:
    with SessionLocal() as session:
        yield session


class ApiClient(TestClient):
    """CSRF 더블 서브밋을 자동 처리하는 테스트 클라이언트."""

    def login(self, username: str, password: str):
        resp = self.post("/api/v1/auth/login",
                         json={"username": username, "password": password})
        if resp.status_code == 200:
            token = self.cookies.get(CSRF_COOKIE)
            if token:
                self.headers[CSRF_HEADER] = token
        return resp

    def logout(self):
        resp = self.post("/api/v1/auth/logout")
        self.headers.pop(CSRF_HEADER, None)
        # 쿠키는 일부러 지우지 않는다 — 서버가 지워 주는지(로그아웃이 실제로 끊기는지) 시험이 보게 한다
        return resp


@pytest.fixture
def client() -> ApiClient:
    with ApiClient(app) as c:
        yield c


def _make_user(db: Session, username: str, display: str, role: str, password: str,
               *, groups: bool = True):
    """시험용 계정.

    groups=True 면 기본 열람 그룹('미분류')에 넣는다. 실제 설치에서도 이관 직후의 모든
    계정이 그 그룹에 있으므로(마이그레이션 c8a2f4e7b015), 이것이 '평소' 상태다.
    그룹 통제 자체를 시험할 때는 groups=False 로 만들어 격리한다.
    """
    from app.core.security import hash_password
    from app.models.group import UserGroup
    from app.models.user import User
    from app.services import group_service
    user = User(username=username, display_name=display, role_code=role,
                password_hash=hash_password(password), is_active=True,
                must_change_password=False)
    db.add(user)
    db.flush()
    if groups:
        group = group_service.ensure_unclassified(db)
        db.add(UserGroup(user_id=user.id, group_id=group.id, is_default=True))
        db.flush()
    return user


@pytest.fixture
def users(db: Session):
    """admin / manager / analyst1 / analyst2 4계정."""
    made = {
        "admin": _make_user(db, "admin", "시스템 관리자", "ADMIN", ADMIN_PW),
        "manager": _make_user(db, "manager1", "김관리", "MANAGER", MANAGER_PW),
        "analyst": _make_user(db, "analyst1", "홍길동", "ANALYST", ANALYST_PW),
        "analyst2": _make_user(db, "analyst2", "김철수", "ANALYST", ANALYST_PW),
    }
    db.commit()
    return {k: {"id": v.id, "username": v.username, "display_name": v.display_name}
            for k, v in made.items()}


# 주의: 아래 세 고정구는 **같은 client 객체**를 쓴다. 한 시험에서 둘을 함께 받으면 나중 로그인이
# 앞 세션을 덮어써 엉뚱한 사람으로 요청하게 된다. 두 사람이 필요하면 ApiClient 를 따로 만든다
# (tests/api/test_security_checklist.py 의 people 고정구 참고).
@pytest.fixture
def admin_client(client: ApiClient, users) -> ApiClient:
    assert client.login("admin", ADMIN_PW).status_code == 200
    return client


@pytest.fixture
def manager_client(client: ApiClient, users) -> ApiClient:
    assert client.login("manager1", MANAGER_PW).status_code == 200
    return client


@pytest.fixture
def analyst_client(client: ApiClient, users) -> ApiClient:
    assert client.login("analyst1", ANALYST_PW).status_code == 200
    return client
