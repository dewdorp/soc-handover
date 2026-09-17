"""초기 비밀번호 미변경 계정의 API 접근 차단.

화면에서만 막으면 API 를 직접 호출해 우회할 수 있다. 서버가 막아야 한다.
열어두는 것은 인증과 비밀번호 변경 경로뿐이다.
"""
from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.user import User

NEW_PW = "Rotate!2026#soc"
TEMP_PW = "Temp!Initial2026#x"


@pytest.fixture
def pending_user(db) -> dict:
    """초기 비밀번호를 아직 바꾸지 않은 ADMIN. 역할이 높아도 막혀야 한다."""
    user = User(username="freshadmin", display_name="신규 관리자", role_code="ADMIN",
                password_hash=hash_password(TEMP_PW), is_active=True,
                must_change_password=True)
    db.add(user)
    db.commit()
    return {"id": user.id, "username": user.username}


@pytest.fixture
def pending_client(client, pending_user):
    assert client.login(pending_user["username"], TEMP_PW).status_code == 200
    return client


class TestAllowedBeforeChange:
    def test_login_succeeds(self, pending_client):
        body = pending_client.get("/api/v1/auth/me").json()
        assert body["must_change_password"] is True

    def test_health_is_unaffected(self, client):
        assert client.get("/api/v1/health").status_code == 200

    def test_can_change_password(self, pending_client):
        resp = pending_client.post("/api/v1/auth/change-password",
                                   json={"current_password": TEMP_PW, "new_password": NEW_PW})
        assert resp.status_code == 204

    def test_can_list_own_sessions(self, pending_client):
        assert pending_client.get("/api/v1/auth/sessions").status_code == 200


class TestBlockedBeforeChange:
    @pytest.mark.parametrize("path", [
        "/api/v1/companies",
        "/api/v1/statuses",
        "/api/v1/priorities",
        "/api/v1/shifts",
        "/api/v1/tags",
        "/api/v1/users",
        "/api/v1/users/lookup",
        "/api/v1/roles",
        "/api/v1/settings",
        "/api/v1/settings/features",
        "/api/v1/handovers",
    ])
    def test_reads_are_blocked(self, pending_client, path):
        resp = pending_client.get(path)
        assert resp.status_code == 403, f"{path} 가 열려 있다"
        assert resp.json()["detail"]["must_change_password"] is True

    def test_writes_are_blocked(self, pending_client):
        resp = pending_client.post("/api/v1/handovers",
                                   json={"company_id": 1, "title": "우회 시도"})
        assert resp.status_code == 403

    def test_admin_only_endpoint_is_blocked_too(self, pending_client):
        """권한은 충분하지만(ADMIN) 비밀번호 게이트가 먼저 막는다."""
        resp = pending_client.post("/api/v1/companies", json={"name": "우회 관계사"})
        assert resp.status_code == 403
        assert resp.json()["detail"].get("must_change_password") is True


class TestAfterChange:
    def test_everything_opens_after_password_change(self, pending_client, pending_user):
        assert pending_client.get("/api/v1/companies").status_code == 403
        assert pending_client.post(
            "/api/v1/auth/change-password",
            json={"current_password": TEMP_PW, "new_password": NEW_PW}).status_code == 204

        pending_client.logout()
        assert pending_client.login(pending_user["username"], NEW_PW).status_code == 200
        assert pending_client.get("/api/v1/auth/me").json()["must_change_password"] is False
        assert pending_client.get("/api/v1/companies").status_code == 200
        assert pending_client.get("/api/v1/handovers").status_code == 200
