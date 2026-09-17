"""권한 게이트가 실제 엔드포인트에서 동작하는지 검증한다(403 기대 경로 포함)."""
from __future__ import annotations

from sqlalchemy import select

from app.models.common import AuditLog
from app.models.user import User
from tests.conftest import ANALYST_PW


class TestUserAdminEndpoints:
    def test_analyst_cannot_list_users(self, analyst_client):
        assert analyst_client.get("/api/v1/users").status_code == 403

    def test_manager_can_list_users(self, manager_client):
        resp = manager_client.get("/api/v1/users")
        assert resp.status_code == 200
        assert resp.json()["total"] == 4

    def test_manager_cannot_create_user(self, manager_client):
        resp = manager_client.post("/api/v1/users", json={
            "username": "newbie", "display_name": "신규", "password": "Str0ng#Welcome2026"})
        assert resp.status_code == 403

    def test_admin_can_create_user(self, admin_client):
        resp = admin_client.post("/api/v1/users", json={
            "username": "newbie", "display_name": "신규", "password": "Str0ng#Welcome2026",
            "role_code": "ANALYST"})
        assert resp.status_code == 201
        assert resp.json()["must_change_password"] is True

    def test_create_rejects_weak_password(self, admin_client):
        resp = admin_client.post("/api/v1/users", json={
            "username": "newbie", "display_name": "신규", "password": "1234"})
        assert resp.status_code == 422

    def test_duplicate_username_conflict(self, admin_client):
        resp = admin_client.post("/api/v1/users", json={
            "username": "analyst1", "display_name": "중복", "password": "Dup!Pass2026aa"})
        assert resp.status_code == 409

    def test_role_change_writes_dedicated_audit(self, admin_client, users, db):
        resp = admin_client.patch(f"/api/v1/users/{users['analyst']['id']}",
                                  json={"role_code": "MANAGER"})
        assert resp.status_code == 200
        acts = db.scalars(select(AuditLog.action)).all()
        assert "ROLE_CHANGE" in acts
        assert "USER_UPDATE" in acts

    def test_admin_cannot_change_own_role(self, admin_client, users):
        resp = admin_client.patch(f"/api/v1/users/{users['admin']['id']}",
                                  json={"role_code": "ANALYST"})
        assert resp.status_code == 422

    def test_admin_cannot_deactivate_self(self, admin_client, users):
        resp = admin_client.delete(f"/api/v1/users/{users['admin']['id']}")
        assert resp.status_code == 422

    def test_deactivate_is_soft(self, admin_client, users, db):
        resp = admin_client.delete(f"/api/v1/users/{users['analyst']['id']}")
        assert resp.status_code == 204
        user = db.get(User, users["analyst"]["id"])
        assert user is not None and user.is_active is False

    def test_password_reset_returns_temp_and_forces_change(self, admin_client, users, client):
        resp = admin_client.post(f"/api/v1/users/{users['analyst']['id']}/reset-password")
        assert resp.status_code == 200
        temp = resp.json()["temporary_password"]
        assert len(temp) > 10
        admin_client.logout()
        assert client.login("analyst1", ANALYST_PW).status_code == 401
        assert client.login("analyst1", temp).status_code == 200

    def test_temp_password_not_in_audit(self, admin_client, users, db):
        resp = admin_client.post(f"/api/v1/users/{users['analyst']['id']}/reset-password")
        temp = resp.json()["temporary_password"]
        rows = db.scalars(select(AuditLog)).all()
        dumped = "".join(str(r.before_value) + str(r.after_value) + str(r.detail)
                         for r in rows)
        assert temp not in dumped


class TestReferenceEndpoints:
    def test_everyone_can_read_reference(self, analyst_client):
        assert analyst_client.get("/api/v1/statuses").status_code == 200
        assert analyst_client.get("/api/v1/priorities").status_code == 200
        assert analyst_client.get("/api/v1/shifts").status_code == 200
        assert analyst_client.get("/api/v1/companies").status_code == 200

    def test_analyst_cannot_create_company(self, analyst_client):
        assert analyst_client.post("/api/v1/companies",
                                   json={"name": "무단생성사"}).status_code == 403

    def test_manager_can_create_company(self, manager_client):
        resp = manager_client.post("/api/v1/companies", json={"name": "A사", "code": "A"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "A사"

    def test_manager_cannot_manage_statuses(self, manager_client):
        resp = manager_client.post("/api/v1/statuses", json={
            "code": "CUSTOM", "name": "사용자정의", "category": "OPEN"})
        assert resp.status_code == 403

    def test_admin_can_add_status(self, admin_client):
        resp = admin_client.post("/api/v1/statuses", json={
            "code": "ESCALATED", "name": "상부보고", "category": "OPEN", "sort_order": 35})
        assert resp.status_code == 201
        codes = [s["code"] for s in admin_client.get("/api/v1/statuses").json()]
        assert "ESCALATED" in codes

    def test_system_status_cannot_be_deleted(self, admin_client):
        resp = admin_client.delete("/api/v1/statuses/NEW")
        assert resp.status_code == 422

    def test_default_statuses_cover_spec(self, analyst_client):
        rows = analyst_client.get("/api/v1/statuses").json()
        names = {r["name"] for r in rows}
        assert {"신규", "진행중", "확인필요", "조치예정", "대기", "보류", "완료", "취소"} <= names
        # 미완료 판정의 단일 기준
        by_code = {r["code"]: r["category"] for r in rows}
        assert by_code["DONE"] == "CLOSED" and by_code["CANCELED"] == "CLOSED"
        assert by_code["IN_PROGRESS"] == "OPEN"

    def test_default_priorities(self, analyst_client):
        rows = analyst_client.get("/api/v1/priorities").json()
        assert [r["name"] for r in rows] == ["긴급", "높음", "보통", "낮음"]
        assert all(r["icon"] for r in rows), "색상 단독 구분 금지 — 아이콘이 있어야 한다"


class TestSystemEndpoints:
    def test_health_is_public(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["database_ok"] is True

    def test_features_requires_auth(self, client):
        assert client.get("/api/v1/settings/features").status_code == 401

    def test_features_reports_ai_disabled_by_default(self, analyst_client):
        body = analyst_client.get("/api/v1/settings/features").json()
        assert body["ai_enabled"] is False
        assert body["ai"]["provider"] == "disabled"
        assert body["ack"]["reack_fields"] == [
            "title", "content", "work_date", "status_code", "priority_code", "assignee_id"]

    def test_settings_list_admin_only(self, analyst_client, manager_client):
        assert analyst_client.get("/api/v1/settings").status_code == 403

    def test_settings_list_for_admin(self, admin_client):
        rows = admin_client.get("/api/v1/settings").json()
        keys = {r["key"] for r in rows}
        assert "ack.reack_fields" in keys
        assert "ai.search_enabled" in keys


class TestSystemEventAudit:
    """backup.ps1 / restore.ps1 이 사용하는 운영 이벤트 기록 경로."""

    def test_backup_event_recorded(self, client, db):
        resp = client.post("/api/v1/audit/system-event",
                           json={"action": "BACKUP",
                                 "detail": {"files": ["soc_handover_20260916.db"]}})
        assert resp.status_code == 201
        row = db.scalar(select(AuditLog).where(AuditLog.action == "BACKUP"))
        assert row is not None
        assert row.detail["files"] == ["soc_handover_20260916.db"]

    def test_restore_event_recorded(self, client):
        resp = client.post("/api/v1/audit/system-event", json={"action": "RESTORE"})
        assert resp.status_code == 201

    def test_arbitrary_action_rejected(self, client):
        resp = client.post("/api/v1/audit/system-event",
                           json={"action": "HANDOVER_DELETE"})
        assert resp.status_code == 422
