"""테스트 공통 설정.

실제 DB(SQLite 파일)와 실제 API 를 사용한다. In-memory mock 으로 대체하지 않는다(§88).
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
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["BACKUP_DIR"] = str(_TMP / "backup")
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
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


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db(_schema):
    """테스트마다 데이터를 비우고 기준 데이터를 다시 구성한다."""
    with SessionLocal() as db:
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
        self.cookies.clear()
        return resp


@pytest.fixture
def client() -> ApiClient:
    with ApiClient(app) as c:
        yield c


def _make_user(db: Session, username: str, display: str, role: str, password: str):
    from app.core.security import hash_password
    from app.models.user import User
    user = User(username=username, display_name=display, role_code=role,
                password_hash=hash_password(password), is_active=True,
                must_change_password=False)
    db.add(user)
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
