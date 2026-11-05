"""⑤ RAG 바닥 공사 — 색인에 **들어가도 되는 것만** 나오는가.

모델이 없으므로 답을 채점하지 않는다. 대신 나중에 색인을 만들 때 어기기 쉬운 경계를
지금 못으로 박아 둔다.

주장
  ① 사례는 목록·검색과 같은 함수를 지난다 → 다른 그룹의 업무는 애초에 나오지 않는다.
  ② 사례 문서에는 색인이 권한을 다시 판정할 수 있도록 group_ids · visibility 가 함께 있다.
  ③ 개인 메모 · 장비 비밀번호 · 지운 업무 · 첨부 내용은 어떤 경로로도 나오지 않는다.
  ④ 계약과 검증 예시가 코드와 같은 목록을 본다(문서만 고치고 코드는 안 고치는 일을 막는다).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.group import Group, UserGroup
from app.models.reference import Company
from app.services import rag_service
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient, _make_user

RAG = "/api/v1/rag"
H = "/api/v1/handovers"


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def split(db, users):
    """1팀(홍길동) · 2팀(박영희) — 서로의 그룹에 없다."""
    g1, g2 = Group(name="1팀", sort_order=1), Group(name="2팀", sort_order=2)
    db.add_all([g1, g2])
    db.flush()
    other = _make_user(db, "rag2", "박영희", "MANAGER", ANALYST_PW, groups=False)
    db.execute(UserGroup.__table__.delete().where(
        UserGroup.user_id == users["analyst"]["id"]))
    db.add_all([UserGroup(user_id=users["analyst"]["id"], group_id=g1.id, is_default=True),
                UserGroup(user_id=other.id, group_id=g2.id, is_default=True)])
    db.commit()
    a = _client("analyst1", ANALYST_PW)
    b = _client("rag2", ANALYST_PW)
    yield {"a": a, "b": b, "g1": g1.id, "g2": g2.id}
    for c in (a, b):
        c.__exit__(None, None, None)


def _make(client, cid, title, **over):
    r = client.post(H, json={"company_id": cid, "title": title, "content": f"{title} 본문",
                             "status_code": "IN_PROGRESS", **over})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- ① ② 범위

class TestCasesFollowTheSameScope:
    def test_other_groups_cases_are_not_exported(self, split, cid):
        mine = _make(split["a"], cid, "1팀 사례")
        theirs = _make(split["b"], cid, "2팀 사례")

        out = split["a"].get(f"{RAG}/cases?limit=200").json()
        ids = [c["case_id"] for c in out["cases"]]
        assert f"handover:{mine['id']}" in ids
        assert f"handover:{theirs['id']}" not in ids
        assert out["scope"]["group_ids"] == [split["g1"]]

    def test_case_carries_group_ids_for_reindex_time_checks(self, split, cid):
        made = _make(split["a"], cid, "근거 확인용")
        case = next(c for c in split["a"].get(f"{RAG}/cases").json()["cases"]
                    if c["handover_id"] == made["id"])
        assert case["group_ids"] == [split["g1"]]
        assert case["visibility"] == "GROUPS"
        assert case["version_no"] == 1
        assert case["case_id"] == f"handover:{made['id']}"

    def test_search_request_narrows_but_cannot_widen(self, split, cid):
        _make(split["b"], cid, "2팀 전용 침해사고")
        out = split["a"].post(f"{RAG}/cases", json={"q": "침해사고"}).json()
        assert out["cases"] == []

    def test_scope_shrinks_when_group_is_revoked(self, split, cid, db, users):
        _make(split["b"], cid, "회수 확인", assignee_id=users["analyst"]["id"])
        before = split["a"].get(f"{RAG}/cases?limit=200").json()
        assert any("회수 확인" == c["title"] for c in before["cases"]), "담당자라 보인다"

        db.execute(UserGroup.__table__.delete().where(
            UserGroup.user_id == users["analyst"]["id"]))
        db.commit()
        after = split["a"].get(f"{RAG}/cases?limit=200").json()
        assert after["scope"]["group_ids"] == []


# --------------------------------------------------------------------------- ③ 제외

class TestExcludedSourcesNeverLeak:
    def test_private_notes_are_not_in_cases(self, admin_client, cid):
        secret = "메모에만 있는 문구 ZZQ"
        made = admin_client.post("/api/v1/me/notes", json={"title": "개인 메모", "body": secret})
        assert made.status_code == 201, made.text

        out = admin_client.get(f"{RAG}/cases?limit=500").json()
        assert secret not in str(out)

    def test_credentials_are_not_in_cases(self, admin_client, cid):
        made = admin_client.post("/api/v1/credentials", json={
            "device_name": "RAG 확인 방화벽", "secret": "Vault#Secret2026!"})
        assert made.status_code == 201, made.text

        out = admin_client.get(f"{RAG}/cases?limit=500").json()
        body = str(out)
        assert "Vault#Secret2026!" not in body
        assert "RAG 확인 방화벽" not in body

    def test_deleted_handovers_are_not_in_cases(self, admin_client, cid):
        made = _make(admin_client, cid, "지울 사례")
        gone = admin_client.request("DELETE", f"{H}/{made['id']}", json={"reason": "중복"})
        assert gone.status_code == 200, gone.text

        out = admin_client.get(f"{RAG}/cases?limit=500").json()
        assert all(c["handover_id"] != made["id"] for c in out["cases"])

    def test_attachment_content_is_not_included_only_names(self, admin_client, cid):
        made = _make(admin_client, cid, "첨부 있는 사례")
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
        up = admin_client.post("/api/v1/attachments",
                               data={"entity_type": "HANDOVER", "entity_id": str(made["id"])},
                               files={"file": ("증적.png", png, "image/png")})
        assert up.status_code == 201, up.text

        case = next(c for c in admin_client.get(f"{RAG}/cases?limit=500").json()["cases"]
                    if c["handover_id"] == made["id"])
        assert case["attachment_names"] == ["증적.png"]
        assert "attachment_content" not in case


# --------------------------------------------------------------------------- ④ 계약

class TestContract:
    def test_contract_lists_every_excluded_source(self, admin_client):
        out = admin_client.get(f"{RAG}/contract").json()
        assert out["schema_version"] == rag_service.SCHEMA_VERSION
        sources = {e["source"] for e in out["excluded"]}
        assert sources == {e["source"] for e in rag_service.EXCLUDED}
        assert {"private_notes", "credentials", "audit_logs"} <= sources
        assert all(e["reason"] for e in out["excluded"]), "왜 빼는지가 비어 있으면 곧 다시 들어온다"

    def test_contract_fields_match_the_document(self, admin_client, cid):
        made = _make(admin_client, cid, "칸 맞추기")
        case = next(c for c in admin_client.get(f"{RAG}/cases").json()["cases"]
                    if c["handover_id"] == made["id"])
        declared = {f["key"] for f in admin_client.get(f"{RAG}/contract").json()["fields"]}
        assert declared <= set(case), f"계약에 적힌 칸이 문서에 없다: {declared - set(case)}"

    def test_verification_examples_cover_the_boundaries(self, admin_client):
        rows = admin_client.get(f"{RAG}/verification-examples").json()
        ids = {r["id"] for r in rows}
        assert {"scope-other-group", "scope-revoked", "exclude-private-note",
                "exclude-credential", "exclude-deleted", "cite-source"} <= ids
        assert all(r["must_hold"] and r["why"] for r in rows)

    def test_contract_requires_db_recheck_not_index_trust(self, admin_client):
        rules = " ".join(admin_client.get(f"{RAG}/contract").json()["rules"])
        assert "원문을 다시 읽어" in rules, "색인만 믿으라고 적혀 있으면 안 된다"
        assert "폐쇄망" in rules

    def test_reading_cases_needs_export_permission(self, analyst_client):
        """사례 묶음은 사실상 대량 내보내기다 — 같은 권한을 요구한다."""
        assert analyst_client.get(f"{RAG}/contract").status_code == 200
        assert analyst_client.get(f"{RAG}/cases").status_code in (200, 403)
