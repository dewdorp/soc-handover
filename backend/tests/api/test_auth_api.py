"""인증 API 테스트: 로그인/세션/CSRF/잠금/감사기록."""
from __future__ import annotations

from sqlalchemy import select

from app.audit import actions
from app.core.middleware import limiter
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE
from app.models.common import AuditLog
from app.models.user import LoginAttempt, RefreshToken, User
from tests.conftest import ADMIN_PW, ANALYST_PW


class TestLogin:
    def test_login_success_sets_cookies(self, client, users):
        resp = client.post("/api/v1/auth/login",
                           json={"username": "admin", "password": ADMIN_PW})
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "admin"
        assert body["role_code"] == "ADMIN"
        assert "user:manage" in body["permissions"]
        assert client.cookies.get(ACCESS_COOKIE)
        assert client.cookies.get(REFRESH_COOKIE)
        assert client.cookies.get(CSRF_COOKIE)

    def test_login_wrong_password(self, client, users):
        resp = client.post("/api/v1/auth/login",
                           json={"username": "admin", "password": "nope-not-it-1!"})
        assert resp.status_code == 401
        # 존재 여부를 구분해서 알려주지 않는다
        assert resp.json()["message"] == "아이디 또는 비밀번호가 올바르지 않습니다."

    def test_login_unknown_user_same_message(self, client, users):
        resp = client.post("/api/v1/auth/login",
                           json={"username": "ghost", "password": "whatever-1!A"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "아이디 또는 비밀번호가 올바르지 않습니다."

    def test_inactive_user_cannot_login(self, client, users, db):
        user = db.scalar(select(User).where(User.username == "analyst1"))
        user.is_active = False
        db.commit()
        assert client.login("analyst1", ANALYST_PW).status_code == 401

    def test_attempts_are_recorded(self, client, users, db):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad-1!Aa"})
        client.login("admin", ADMIN_PW)
        rows = db.scalars(select(LoginAttempt).order_by(LoginAttempt.id)).all()
        assert [r.success for r in rows] == [False, True]

    def test_audit_written(self, client, users, db):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad-1!Aa"})
        client.login("admin", ADMIN_PW)
        acts = db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
        assert actions.LOGIN_FAILURE in acts
        assert actions.LOGIN_SUCCESS in acts


class TestLockout:
    def test_account_locks_after_repeated_failures(self, client, users):
        for _ in range(5):
            r = client.post("/api/v1/auth/login",
                            json={"username": "analyst1", "password": "wrong-1!Aa"})
            assert r.status_code == 401
        # 올바른 비밀번호여도 잠금 상태에서는 로그인 불가
        resp = client.post("/api/v1/auth/login",
                           json={"username": "analyst1", "password": ANALYST_PW})
        assert resp.status_code == 401
        assert "잠겼" in resp.json()["message"]

    def test_successful_login_resets_counter(self, client, users, db):
        for _ in range(3):
            client.post("/api/v1/auth/login",
                        json={"username": "analyst1", "password": "wrong-1!Aa"})
        assert client.login("analyst1", ANALYST_PW).status_code == 200
        user = db.scalar(select(User).where(User.username == "analyst1"))
        assert user.failed_login_count == 0
        assert user.locked_until is None


class TestSessionLifecycle:
    def test_me_requires_auth(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_returns_profile(self, analyst_client):
        body = analyst_client.get("/api/v1/auth/me").json()
        assert body["username"] == "analyst1"
        assert body["role_code"] == "ANALYST"
        assert "user:manage" not in body["permissions"]

    def test_refresh_rotates_token(self, client, users, db):
        client.login("admin", ADMIN_PW)
        first = client.cookies.get(REFRESH_COOKIE)
        assert client.post("/api/v1/auth/refresh").status_code == 200
        second = client.cookies.get(REFRESH_COOKIE)
        assert first != second
        revoked = db.scalars(select(RefreshToken).where(
            RefreshToken.revoked_at.is_not(None))).all()
        assert len(revoked) == 1

    def test_reused_refresh_token_revokes_all(self, client, users, db):
        client.login("admin", ADMIN_PW)
        stolen = client.cookies.get(REFRESH_COOKIE)
        client.post("/api/v1/auth/refresh")           # 정상 회전
        client.cookies.set(REFRESH_COOKIE, stolen)     # 탈취 토큰 재사용
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401
        active = db.scalars(select(RefreshToken).where(
            RefreshToken.revoked_at.is_(None))).all()
        assert active == []

    def test_logout_revokes_and_clears(self, client, users, db):
        client.login("admin", ADMIN_PW)
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert db.scalars(select(RefreshToken).where(
            RefreshToken.revoked_at.is_(None))).all() == []

    def test_sessions_listed(self, admin_client):
        rows = admin_client.get("/api/v1/auth/sessions").json()
        assert len(rows) == 1
        assert rows[0]["current"] is True


class TestCsrf:
    def test_state_change_without_csrf_header_is_blocked(self, client, users):
        client.login("admin", ADMIN_PW)
        client.headers.pop(CSRF_HEADER, None)
        resp = client.post("/api/v1/companies", json={"name": "CSRF테스트사"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "csrf_failed"

    def test_wrong_csrf_header_is_blocked(self, client, users):
        client.login("admin", ADMIN_PW)
        client.headers[CSRF_HEADER] = "tampered-value"
        resp = client.post("/api/v1/companies", json={"name": "CSRF테스트사"})
        assert resp.status_code == 403

    def test_safe_method_needs_no_csrf(self, client, users):
        client.login("admin", ADMIN_PW)
        client.headers.pop(CSRF_HEADER, None)
        assert client.get("/api/v1/companies").status_code == 200


class TestPasswordChange:
    def test_change_password_flow(self, client, users):
        client.login("analyst1", ANALYST_PW)
        new_pw = "Renewed!Pass2026"
        resp = client.post("/api/v1/auth/change-password",
                           json={"current_password": ANALYST_PW, "new_password": new_pw})
        assert resp.status_code == 204
        client.cookies.clear()
        assert client.login("analyst1", ANALYST_PW).status_code == 401
        assert client.login("analyst1", new_pw).status_code == 200

    def test_rejects_weak_password(self, client, users):
        client.login("analyst1", ANALYST_PW)
        resp = client.post("/api/v1/auth/change-password",
                           json={"current_password": ANALYST_PW, "new_password": "weak"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["problems"]

    def test_rejects_wrong_current(self, client, users):
        client.login("analyst1", ANALYST_PW)
        resp = client.post("/api/v1/auth/change-password",
                           json={"current_password": "nope-1!Aa", "new_password": "Renewed!Pass2026"})
        assert resp.status_code == 422


class TestRateLimit:
    def test_login_rate_limited(self, client, users):
        limiter.rules = (("/api/v1/auth/login", 3, 300),)
        for _ in range(3):
            client.post("/api/v1/auth/login", json={"username": "x", "password": "y-1!Aa"})
        resp = client.post("/api/v1/auth/login", json={"username": "x", "password": "y-1!Aa"})
        assert resp.status_code == 429
        assert resp.headers["Retry-After"]
