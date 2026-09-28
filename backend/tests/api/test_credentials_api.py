"""장비 비밀번호 보관 — 등록 · 보기 · 범위 · 변경 이력 (현장 요청).

여기서 지켜야 할 선은 분명하다.
  · 비밀번호 값은 /reveal 말고는 어떤 응답에도 나오지 않는다.
  · DB 에는 암호문만 있다(덤프가 새어도 비밀번호는 안 나온다).
  · 볼 때마다 본인 확인 + 감사 기록.
  · 남의 개인 항목은 있다는 사실조차 보이지 않는다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit import actions
from app.models.common import AuditLog
from app.models.credential import KEEP_VERSIONS, Credential
from app.models.reference import Company
from app.main import app
from tests.conftest import ADMIN_PW, ANALYST_PW, MANAGER_PW, ApiClient

C = "/api/v1/credentials"


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    clients = {"hong": _client("analyst1", ANALYST_PW), "kim": _client("analyst2", ANALYST_PW),
               "mgr": _client("manager1", MANAGER_PW), "admin": _client("admin", ADMIN_PW)}
    yield {**clients, "ids": users}
    for c in clients.values():
        c.__exit__(None, None, None)


@pytest.fixture
def cid(db) -> int:
    company = Company(name="A보안")
    db.add(company)
    db.commit()
    return company.id


def _make(client, cid, **over) -> dict:
    body = {"company_id": cid, "device_name": "방화벽-01", "access_method": "SSH 10.0.0.1:22",
            "username": "socadmin", "secret": "Fw!2026#secret", **over}
    resp = client.post(C, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestSecretNeverLeaks:
    def test_secret_is_not_in_any_listing(self, people, cid):
        hong = people["hong"]
        made = _make(hong, cid)
        assert "secret" not in made

        for text in (hong.get(C).text, hong.get(f"{C}/{made['id']}").text,
                     hong.get(f"{C}/{made['id']}/versions").text):
            assert "Fw!2026#secret" not in text, "비밀번호가 목록 · 상세 · 이력에 섞여 나오면 안 된다"

    def test_database_holds_ciphertext_only(self, people, cid, db):
        made = _make(people["hong"], cid)
        row = db.get(Credential, made["id"])
        assert row.secret_cipher and b"Fw!2026#secret" not in row.secret_cipher
        assert len(row.secret_cipher) > 13, "키버전 + nonce + 본문"

    def test_reveal_needs_my_own_password(self, people, cid, db):
        hong = people["hong"]
        made = _make(hong, cid)

        wrong = hong.post(f"{C}/{made['id']}/reveal", json={"password": "틀린비밀번호"})
        assert wrong.status_code == 403
        assert "본인 비밀번호" in wrong.json()["message"]

        got = hong.post(f"{C}/{made['id']}/reveal", json={"password": ANALYST_PW})
        assert got.status_code == 200, got.text
        assert got.json()["secret"] == "Fw!2026#secret"

        seen = [(l.action, l.result) for l in db.scalars(
            select(AuditLog).where(AuditLog.action.in_(
                (actions.CREDENTIAL_REVEAL, actions.CREDENTIAL_REVEAL_DENIED))).order_by(AuditLog.id))]
        assert seen == [(actions.CREDENTIAL_REVEAL_DENIED, "FAILURE"),
                        (actions.CREDENTIAL_REVEAL, "SUCCESS")], "본 것도 못 본 것도 남는다"

    def test_every_reveal_is_recorded(self, people, cid, db):
        made = _make(people["hong"], cid)
        for _ in range(3):
            assert people["hong"].post(f"{C}/{made['id']}/reveal",
                                       json={"password": ANALYST_PW}).status_code == 200
        rows = db.scalars(select(AuditLog).where(
            AuditLog.action == actions.CREDENTIAL_REVEAL)).all()
        assert len(rows) == 3
        assert rows[0].detail["device_name"] == "방화벽-01" and rows[0].resource_id == str(made["id"])


class TestScope:
    def test_shared_is_visible_to_everyone(self, people, cid):
        made = _make(people["hong"], cid, device_name="공용 스위치")
        listed = people["kim"].get(C).json()
        assert [r["device_name"] for r in listed] == ["공용 스위치"]
        assert people["kim"].post(f"{C}/{made['id']}/reveal",
                                  json={"password": ANALYST_PW}).status_code == 200

    def test_personal_is_invisible_to_others(self, people, cid):
        made = _make(people["hong"], cid, scope="PERSONAL", device_name="내 노트북")
        assert people["kim"].get(C).json() == [], "남의 개인 항목은 목록에 없다"
        # 있다는 사실조차 알려 주지 않는다(403 이 아니라 404)
        assert people["kim"].get(f"{C}/{made['id']}").status_code == 404
        assert people["kim"].post(f"{C}/{made['id']}/reveal",
                                  json={"password": ANALYST_PW}).status_code == 404
        assert people["mgr"].get(f"{C}/{made['id']}").status_code == 404, "관리자도 못 본다"

        mine = people["hong"].get(C).json()
        assert [r["device_name"] for r in mine] == ["내 노트북"]

    def test_scope_can_be_switched(self, people, cid):
        made = _make(people["hong"], cid, scope="PERSONAL")
        assert people["kim"].get(C).json() == []
        people["hong"].patch(f"{C}/{made['id']}", json={"scope": "SHARED"})
        assert len(people["kim"].get(C).json()) == 1


class TestEditRules:
    def test_owner_and_manager_can_edit_others_cannot(self, people, cid):
        made = _make(people["hong"], cid)
        assert people["kim"].patch(f"{C}/{made['id']}", json={"note": "남이 고침"}).status_code == 403
        assert people["kim"].delete(f"{C}/{made['id']}").status_code == 403
        assert people["hong"].patch(f"{C}/{made['id']}", json={"note": "본인"}).status_code == 200
        assert people["mgr"].patch(f"{C}/{made['id']}", json={"note": "관리자"}).status_code == 200
        assert people["mgr"].delete(f"{C}/{made['id']}").status_code == 204
        assert people["hong"].get(f"{C}/{made['id']}").status_code == 404

    def test_can_edit_flag_matches_the_rule(self, people, cid):
        made = _make(people["hong"], cid)
        assert people["hong"].get(f"{C}/{made['id']}").json()["can_edit"] is True
        assert people["kim"].get(f"{C}/{made['id']}").json()["can_edit"] is False
        assert people["mgr"].get(f"{C}/{made['id']}").json()["can_edit"] is True

    def test_device_name_and_secret_are_required(self, people, cid):
        assert people["hong"].post(C, json={"device_name": "", "secret": "x"}).status_code == 422
        assert people["hong"].post(C, json={"device_name": "장비", "secret": ""}).status_code == 422
        made = _make(people["hong"], cid)
        assert people["hong"].patch(f"{C}/{made['id']}",
                                    json={"device_name": "  "}).status_code == 422

    def test_unknown_company_is_refused(self, people):
        resp = people["hong"].post(C, json={"company_id": 999_999, "device_name": "장비",
                                            "secret": "x"})
        assert resp.status_code == 422


class TestHistory:
    def test_changing_the_secret_keeps_the_previous_one(self, people, cid):
        hong = people["hong"]
        made = _make(hong, cid)
        assert hong.patch(f"{C}/{made['id']}",
                          json={"secret": "New!2026#pass", "change_note": "정기 교체"}).status_code == 200

        now_value = hong.post(f"{C}/{made['id']}/reveal", json={"password": ANALYST_PW}).json()
        assert now_value["secret"] == "New!2026#pass" and now_value["version_no"] == 2

        history = hong.get(f"{C}/{made['id']}/versions").json()
        assert [h["version_no"] for h in history] == [1]
        assert history[0]["changed_fields"] == ["secret"]
        assert history[0]["changed_by"] == "홍길동" and history[0]["change_note"] == "정기 교체"
        assert history[0]["has_secret"] is True

        old = hong.post(f"{C}/{made['id']}/versions/1/reveal", json={"password": ANALYST_PW})
        assert old.status_code == 200
        assert old.json()["secret"] == "Fw!2026#secret", "장비에 새 값이 안 먹으면 되돌릴 수 있어야 한다"

    def test_metadata_change_is_recorded_without_a_secret(self, people, cid):
        hong = people["hong"]
        made = _make(hong, cid)
        hong.patch(f"{C}/{made['id']}", json={"device_name": "방화벽-02", "username": "admin2"})
        history = hong.get(f"{C}/{made['id']}/versions").json()
        assert sorted(history[0]["changed_fields"]) == ["device_name", "username"]
        assert history[0]["has_secret"] is False
        assert hong.post(f"{C}/{made['id']}/versions/1/reveal",
                         json={"password": ANALYST_PW}).status_code == 404

    def test_only_recent_secrets_are_kept(self, people, cid):
        hong = people["hong"]
        made = _make(hong, cid)
        for i in range(KEEP_VERSIONS + 2):
            assert hong.patch(f"{C}/{made['id']}",
                              json={"secret": f"Pass!{i}#2026"}).status_code == 200

        history = hong.get(f"{C}/{made['id']}/versions").json()
        kept = [h["version_no"] for h in history if h["has_secret"]]
        assert len(kept) == KEEP_VERSIONS, f"최근 {KEEP_VERSIONS}개만 값을 들고 있는다"
        assert len(history) == KEEP_VERSIONS + 2, "누가 언제 바꿨는지는 전부 남는다"
        oldest = min(h["version_no"] for h in history)
        assert hong.post(f"{C}/{made['id']}/versions/{oldest}/reveal",
                         json={"password": ANALYST_PW}).status_code == 404

    def test_reveal_of_old_secret_is_audited_too(self, people, cid, db):
        hong = people["hong"]
        made = _make(hong, cid)
        hong.patch(f"{C}/{made['id']}", json={"secret": "New!2026#pass"})
        hong.post(f"{C}/{made['id']}/versions/1/reveal", json={"password": ANALYST_PW})
        row = db.scalar(select(AuditLog).where(AuditLog.action == actions.CREDENTIAL_REVEAL)
                        .order_by(AuditLog.id.desc()))
        assert row.detail["version_no"] == 1 and row.detail["is_current"] is False


class TestSearch:
    def test_list_can_be_narrowed(self, people, cid):
        hong = people["hong"]
        _make(hong, cid, device_name="방화벽-01", username="socadmin")
        _make(hong, cid, device_name="IPS-02", username="ipsuser", access_method="웹 https://10.0.0.2")
        assert [r["device_name"] for r in hong.get(C, params={"q": "IPS"}).json()] == ["IPS-02"]
        assert [r["device_name"] for r in hong.get(C, params={"q": "socadmin"}).json()] == ["방화벽-01"]
        assert len(hong.get(C, params={"company_id": cid}).json()) == 2
        assert hong.get(C, params={"scope": "PERSONAL"}).json() == []
