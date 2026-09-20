"""SECURITY.md §11 보안 테스트 항목 — 한 곳에서 다시 확인한다(Phase 10).

개별 규칙은 각 기능 테스트에도 있지만, 보안 점검은 '무엇을 확인했는가'가 한눈에 보여야 한다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.common import AuditLog
from app.models.handover import Handover, HandoverVersion
from app.models.user import User
from app.main import app
from app.models.reference import Company
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient

import pytest

H = "/api/v1/handovers"


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _client(username: str, password: str) -> ApiClient:
    """계정마다 별도 클라이언트 — admin_client · analyst_client 고정구는 같은 객체라 세션이 덮인다."""
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    clients = {"admin": _client("admin", ADMIN_PW), "analyst": _client("analyst1", ANALYST_PW)}
    yield {**clients, "ids": users}
    for c in clients.values():
        c.__exit__(None, None, None)


def _handover(client, cid, title="보안 점검용") -> dict:
    r = client.post(H, json={"company_id": cid, "title": title, "content": title,
                             "status_code": "IN_PROGRESS"})
    assert r.status_code == 201, r.text
    return r.json()


# 1 · 2. 권한 · 남의 자원 직접 접근(IDOR)

class TestOwnership:
    def test_cannot_read_or_change_other_users_notification(self, people, cid):
        admin_client, analyst_client, users = people["admin"], people["analyst"], people["ids"]
        # 실제 흐름으로 알림을 만든다: 관리자가 근무자를 담당자로 지정하면 그 근무자에게 알림이 간다
        admin_client.post(H, json={"company_id": cid, "title": "담당 지정", "content": "x",
                                   "status_code": "NEW", "assignee_id": users["analyst"]["id"]})
        mine = analyst_client.get("/api/v1/notifications").json()
        assert mine, "담당자에게 알림이 간다"
        target = mine[0]["id"]
        assert all(n["id"] != target for n in admin_client.get("/api/v1/notifications").json()), \
            "남의 알림은 목록에 나오지 않는다"
        assert admin_client.post(f"/api/v1/notifications/{target}/read").status_code in (403, 404)

    def test_cannot_use_other_users_personal_saved_view(self, people):
        admin_client, analyst_client = people["admin"], people["analyst"]
        view = admin_client.post("/api/v1/saved-views",
                                 json={"name": "관리자 개인 보기", "scope": "PERSONAL",
                                       "state": {"filters": []}}).json()
        assert all(v["id"] != view["id"] for v in analyst_client.get("/api/v1/saved-views").json())
        assert analyst_client.delete(f"/api/v1/saved-views/{view['id']}").status_code in (403, 404)

    def test_cannot_touch_other_users_basket(self, people, cid):
        admin_client, analyst_client = people["admin"], people["analyst"]
        h = _handover(admin_client, cid)
        admin_client.post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [h["id"]]})
        basket = admin_client.get("/api/v1/shift-handovers/basket").json()
        item_id = basket["items"][0]["item_id"]
        assert analyst_client.delete(f"/api/v1/shift-handovers/basket/items/{item_id}").status_code in (403, 404)
        assert admin_client.get("/api/v1/shift-handovers/basket").json()["items"], "남이 지우지 못한다"


# 3. 필터 DSL 인젝션 — test_search_api 에도 있으나 점검 목록으로 한 번 더

class TestDslInjection:
    def test_unknown_field_is_rejected(self, admin_client):
        r = admin_client.post(f"{H}/search",
                              json={"filters": [{"field": "id; DROP TABLE handovers", "op": "eq", "value": 1}]})
        assert r.status_code == 422

    def test_unknown_operator_is_rejected(self, admin_client):
        r = admin_client.post(f"{H}/search",
                              json={"filters": [{"field": "title", "op": "; DELETE FROM", "value": "x"}]})
        assert r.status_code == 422

    def test_sort_field_is_whitelisted(self, admin_client):
        r = admin_client.post(f"{H}/search", json={"sort": [{"field": "password_hash", "dir": "asc"}]})
        assert r.status_code == 422


# 7. Version 불변성

class TestVersionImmutability:
    def test_no_api_changes_or_deletes_a_version(self, admin_client, cid, db):
        h = _handover(admin_client, cid)
        admin_client.patch(f"{H}/{h['id']}", json={"expected_version": 1, "content": "v2"})
        versions = admin_client.get(f"{H}/{h['id']}/versions").json()
        assert len(versions) == 2
        for method in ("patch", "put", "delete"):
            r = getattr(admin_client, method)(f"{H}/{h['id']}/versions/1")
            assert r.status_code in (404, 405), f"{method} {r.status_code}"
        assert len(admin_client.get(f"{H}/{h['id']}/versions").json()) == 2
        # 복원도 과거를 고치지 않고 새 버전을 만든다
        admin_client.post(f"{H}/{h['id']}/versions/1/restore",
                          json={"expected_version": 2, "change_reason": "되돌림"})
        rows = db.scalars(select(HandoverVersion).where(HandoverVersion.handover_id == h["id"])
                          .order_by(HandoverVersion.version_no)).all()
        assert [v.version_no for v in rows] == [1, 2, 3]
        assert rows[0].after_data["content"] == "보안 점검용", "v1 은 그대로다"


# 8. Soft delete 우회 불가

class TestSoftDelete:
    def test_analyst_cannot_see_deleted_handover(self, people, cid, db):
        admin_client, analyst_client = people["admin"], people["analyst"]
        h = _handover(admin_client, cid, "지울 건")
        removed = admin_client.request("DELETE", f"{H}/{h['id']}", json={"reason": "점검"})
        assert removed.status_code == 200, removed.text
        assert analyst_client.get(f"{H}/{h['id']}").status_code == 404, "존재 자체를 드러내지 않는다"
        listed = analyst_client.post(f"{H}/search", json={"page": 1, "size": 50}).json()
        assert all(i["id"] != h["id"] for i in listed["items"])
        assert analyst_client.post(f"{H}/search", json={"include_deleted": True}).status_code == 403
        assert db.get(Handover, h["id"]).is_deleted is True, "행은 남는다(증적)"


# 9. 비밀번호 · 토큰이 응답 · 감사 · 로그에 남지 않는다

class TestSecretsNotLeaked:
    def test_password_is_not_in_response_or_audit(self, admin_client, db):
        secret = "Leak#Check2026!zq"
        created = admin_client.post("/api/v1/users", json={
            "username": "leakcheck", "display_name": "유출점검", "password": secret,
            "role_code": "ANALYST"})
        assert created.status_code == 201
        assert secret not in created.text and "password_hash" not in created.text

        me = admin_client.get("/api/v1/auth/me").text
        assert "password_hash" not in me and secret not in me

        for log in db.scalars(select(AuditLog)):
            blob = f"{log.before_value} {log.after_value} {log.detail}"
            assert secret not in blob, f"{log.action} 에 비밀번호가 남았다"
        user = db.scalar(select(User).where(User.username == "leakcheck"))
        assert user.password_hash.startswith("$argon2"), "해시만 저장한다"

    def test_reset_password_is_shown_once_and_not_audited(self, admin_client, users, db):
        temp = admin_client.post(f"/api/v1/users/{users['analyst']['id']}/reset-password").json()
        assert temp["temporary_password"]
        for log in db.scalars(select(AuditLog).where(AuditLog.action == "PASSWORD_RESET")):
            assert temp["temporary_password"] not in f"{log.after_value} {log.detail}"


# 10. AI 경로 없음

class TestNoAiRoutes:
    def test_ai_paths_do_not_exist(self, admin_client):
        for path in ("/api/v1/ai/status", "/api/v1/ai/search", "/api/v1/ai/reindex"):
            assert admin_client.get(path).status_code == 404
            assert admin_client.post(path, json={}).status_code in (404, 405)
