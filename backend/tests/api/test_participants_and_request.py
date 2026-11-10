"""⑤ 복수 담당 · 필수 인수자 · 참고 전파 · CERT 전체 전파 · 분석 의뢰 흐름.

주장
  ① 한 사람은 한 역할만 가진다. 담당으로도 참고로도 들어오면 **강한 쪽**만 남는다
     — 두 줄이 남으면 확인 숫자가 두 번 세어지고 알림이 두 번 간다.
  ② 확인 의무는 역할이 정한다. 참고(FYI)는 미확인으로 잡히지 않는다.
  ③ 전파는 **누르기 전에** 담당 N / 필수 N / 참고 N / 제외 M 을 보여 주고,
     누른 결과가 그 숫자와 같다.
  ④ 전파는 **공개 범위를 넓히지 않는다** — 사람을 거는 것이지 글을 여는 것이 아니다.
  ⑤ 의뢰 → 접수 → 회신. 되돌릴 수 없고, 내용 없는 회신은 받지 않는다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.group import Group, UserGroup
from app.models.reference import Company
from tests.conftest import ADMIN_PW, ANALYST_PW, MANAGER_PW, ApiClient, _make_user

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
def cert(db, users):
    """CERT 그룹에 세 사람 — 전파 대상. 관리자도 그 그룹에 넣어 숫자를 볼 수 있게 한다."""
    group = Group(name="CERT", description="침해사고 대응", sort_order=1)
    db.add(group)
    db.flush()
    members = [
        _make_user(db, "cert1", "정대응", "ANALYST", ANALYST_PW, groups=False),
        _make_user(db, "cert2", "한분석", "ANALYST", ANALYST_PW, groups=False),
        _make_user(db, "cert3", "오포렌식", "ANALYST", ANALYST_PW, groups=False),
    ]
    db.flush()
    for m in members:
        db.add(UserGroup(user_id=m.id, group_id=group.id, is_default=True))
    db.add(UserGroup(user_id=users["admin"]["id"], group_id=group.id))
    db.commit()
    return {"group_id": group.id, "ids": [m.id for m in members],
            "names": [m.display_name for m in members]}


def _make(client, cid, title="전파 확인용", **over) -> dict:
    # 전파 권한 불확대 테스트는 특정 그룹에 게시한 글을 기준으로 한다.
    if "visibility" not in over and "group_ids" not in over:
        groups = client.get("/api/v1/groups/mine").json()
        own = next((g["id"] for g in groups if g.get("is_default")), None)
        if own is not None:
            over = {**over, "visibility": "GROUPS", "group_ids": [own]}
    r = client.post(H, json={"company_id": cid, "title": title, "content": title,
                             "status_code": "IN_PROGRESS", **over})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- ① ② 역할

class TestRolesAreDeduplicated:
    def test_same_person_twice_keeps_the_stronger_role(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        uid = users["analyst"]["id"]
        resp = admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": uid, "role": "FYI"},
            {"user_id": uid, "role": "CO_OWNER"},
        ]})
        assert resp.status_code == 200, resp.text
        rows = [p for p in resp.json()["participants"] if p["user_id"] == uid]
        assert len(rows) == 1, "같은 사람이 두 줄로 남으면 안 된다"
        assert rows[0]["role"] == "CO_OWNER"

    def test_only_one_owner(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        resp = admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst"]["id"], "role": "OWNER"},
            {"user_id": users["manager"]["id"], "role": "OWNER"},
        ]})
        assert resp.status_code == 422, resp.text
        assert "대표 담당" in resp.json()["message"]

    def test_owner_matches_the_assignee_field(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst"]["id"], "role": "OWNER"}]})
        detail = admin_client.get(f"{H}/{hid}").json()
        assert detail["assignee"]["id"] == users["analyst"]["id"], \
            "목록의 담당자와 상세의 대표 담당이 다른 이름이면 안 된다"

    def test_fyi_does_not_create_a_pending_ack(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst"]["id"], "role": "FYI"},
            {"user_id": users["manager"]["id"], "role": "REQUIRED"},
        ]})
        acks = {a["user_id"]: a["state"] for a in
                admin_client.get(f"{H}/{hid}/acknowledgements").json()}
        assert users["manager"]["id"] in acks, "필수 인수자는 확인 대기로 잡힌다"
        assert users["analyst"]["id"] not in acks, "참고는 확인 대기로 잡히지 않는다"

    def test_counts_split_by_role(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        resp = admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst"]["id"], "role": "OWNER"},
            {"user_id": users["manager"]["id"], "role": "CO_OWNER"},
            {"user_id": users["analyst2"]["id"], "role": "FYI"},
        ]})
        counts = resp.json()["counts"]
        assert (counts["owner"], counts["co_owner"], counts["fyi"]) == (1, 1, 1)
        assert counts["must_ack"] == 2, "참고는 확인해야 할 사람 수에 들어가지 않는다"
        assert counts["total"] == 3

    def test_replacing_removes_people(self, admin_client, cid, users):
        hid = _make(admin_client, cid)["id"]
        admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst"]["id"], "role": "REQUIRED"},
            {"user_id": users["manager"]["id"], "role": "FYI"}]})
        after = admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["manager"]["id"], "role": "FYI"}]}).json()
        assert [p["user_id"] for p in after["participants"]] == [users["manager"]["id"]]

    def test_inactive_account_is_refused(self, admin_client, cid, users, db):
        from app.models.user import User

        hid = _make(admin_client, cid)["id"]
        user = db.get(User, users["analyst2"]["id"])
        user.is_active = False
        db.commit()
        resp = admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": users["analyst2"]["id"], "role": "FYI"}]})
        assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- ③ ④ 전파

class TestPropagation:
    def test_preview_shows_who_and_how_many(self, admin_client, cid, cert):
        hid = _make(admin_client, cid, title="CERT 전파 대상")["id"]
        preview = admin_client.post(f"{H}/{hid}/propagate/preview", json={
            "group_ids": [cert["group_id"]], "role": "FYI"})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["groups"][0]["name"] == "CERT"
        assert body["add_count"] == 4, "CERT 구성원 3명 + 관리자"
        assert body["after"]["fyi"] >= 3
        assert "공개 범위" in body["visibility_note"]

    def test_excluded_people_are_shown_by_name(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        body = admin_client.post(f"{H}/{hid}/propagate/preview", json={
            "group_ids": [cert["group_id"]], "role": "FYI",
            "exclude_user_ids": [cert["ids"][0]]}).json()
        assert body["excluded_count"] == 1
        assert cert["names"][0] in body["excluded_by_hand"]
        assert cert["ids"][0] not in body["add_user_ids"]

    def test_already_stronger_role_is_not_downgraded(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        admin_client.put(f"{H}/{hid}/participants", json={"participants": [
            {"user_id": cert["ids"][0], "role": "CO_OWNER"}]})

        body = admin_client.post(f"{H}/{hid}/propagate/preview", json={
            "group_ids": [cert["group_id"]], "role": "FYI"}).json()
        assert any(cert["names"][0] in x for x in body["excluded_already_stronger"])

        applied = admin_client.post(f"{H}/{hid}/propagate", json={
            "group_ids": [cert["group_id"]], "role": "FYI"}).json()
        roles = {p["user_id"]: p["role"] for p in applied["participants"]}
        assert roles[cert["ids"][0]] == "CO_OWNER", "참고로 끌어내리면 안 된다"

    def test_applying_matches_the_preview(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        body = {"group_ids": [cert["group_id"]], "role": "FYI"}
        preview = admin_client.post(f"{H}/{hid}/propagate/preview", json=body).json()
        applied = admin_client.post(f"{H}/{hid}/propagate", json=body).json()
        assert applied["add_count"] == preview["add_count"]
        assert applied["after"] == preview["after"]
        assert applied["applied"] is True
        assert len(applied["participants"]) == preview["after"]["total"]

    def test_propagation_does_not_widen_the_public_scope(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        before = admin_client.get(f"{H}/{hid}").json()
        admin_client.post(f"{H}/{hid}/propagate", json={
            "group_ids": [cert["group_id"]], "role": "FYI"})
        after = admin_client.get(f"{H}/{hid}").json()
        assert after["visibility"] == before["visibility"] == "GROUPS"
        assert after["group_names"] == before["group_names"], \
            "전파는 사람을 거는 것이지 글을 여는 것이 아니다"

    def test_propagated_person_can_see_it_but_others_cannot(self, admin_client, cid, cert, db,
                                                            users):
        """전파로 걸린 사람은 그룹이 달라도 본다. 걸리지 않은 사람은 못 본다."""
        hid = _make(admin_client, cid, title="전파로만 보이는 건")["id"]
        outsider = _make_user(db, "outsider1", "밖에있음", "ANALYST", ANALYST_PW, groups=False)
        db.commit()

        admin_client.post(f"{H}/{hid}/propagate", json={
            "group_ids": [cert["group_id"]], "role": "FYI"})

        inside = _client("cert1", ANALYST_PW)
        outside = _client("outsider1", ANALYST_PW)
        try:
            assert inside.get(f"{H}/{hid}").status_code == 200
            assert outside.get(f"{H}/{hid}").status_code == 404
            assert outsider.id
        finally:
            inside.__exit__(None, None, None)
            outside.__exit__(None, None, None)

    def test_propagation_is_audited_with_counts(self, admin_client, cid, cert):
        from app.core.time import today

        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/propagate", json={
            "group_ids": [cert["group_id"]], "role": "FYI"})
        day = today().isoformat()
        rows = admin_client.post("/api/v1/audit/search", json={
            "start": f"{day}T00:00:00+09:00", "end": f"{day}T23:59:59+09:00",
            "actions": ["HANDOVER_PROPAGATE"], "size": 10}).json()
        assert rows["total"] >= 1, rows
        after = rows["items"][0]["after_value"]
        assert after["groups"] == ["CERT"]
        assert after["added"] >= 3


# --------------------------------------------------------------------------- ⑤ 분석 의뢰

class TestAnalysisRequest:
    def test_request_accept_answer(self, admin_client, cid, cert):
        hid = _make(admin_client, cid, title="의뢰 흐름")["id"]
        asked = admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": cert["ids"][:2], "note": "C2 통신 로그 분석 부탁드립니다."})
        assert asked.status_code == 200, asked.text
        assert asked.json()["state"] == "REQUESTED"
        assert asked.json()["request_note"].startswith("C2")

        # 받은 사람은 필수 인수자로 걸린다 — 접수를 추적할 사람이 있어야 한다
        people = admin_client.get(f"{H}/{hid}/participants").json()
        roles = {p["user_id"]: p["role"] for p in people["participants"]}
        assert roles[cert["ids"][0]] == "REQUIRED"

        cert1 = _client("cert1", ANALYST_PW)
        try:
            took = cert1.post(f"{H}/{hid}/request/accept", json={"note": "확인하겠습니다"})
            assert took.status_code == 200, took.text
            assert took.json()["state"] == "ACCEPTED"
            assert took.json()["accepted_at"]

            done = cert1.post(f"{H}/{hid}/request/answer", json={
                "note": "내부 PC 1대가 알려진 C2 로 통신. 망분리 완료, 이미지 확보."})
            assert done.status_code == 200, done.text
            assert done.json()["state"] == "ANSWERED"
            assert "망분리" in done.json()["answer_note"]
        finally:
            cert1.__exit__(None, None, None)

    def test_cannot_accept_without_a_request(self, admin_client, cid):
        hid = _make(admin_client, cid)["id"]
        resp = admin_client.post(f"{H}/{hid}/request/accept", json={})
        assert resp.status_code == 409, resp.text
        assert "바꿀 수 없습니다" in resp.json()["message"]

    def test_answer_without_content_is_refused(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "봐 주세요"})
        resp = admin_client.post(f"{H}/{hid}/request/answer", json={"note": "   "})
        assert resp.status_code == 422, resp.text

    def test_can_answer_without_accepting(self, admin_client, cid, cert):
        """간단한 건은 보자마자 답한다 — 접수를 건너뛰는 것은 막지 않는다."""
        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "간단한 확인"})
        resp = admin_client.post(f"{H}/{hid}/request/answer", json={"note": "오탐입니다."})
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "ANSWERED"

    def test_cannot_go_backwards(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "의뢰"})
        admin_client.post(f"{H}/{hid}/request/answer", json={"note": "회신"})
        back = admin_client.post(f"{H}/{hid}/request/accept", json={})
        assert back.status_code == 409, "회신한 건을 다시 접수로 되돌릴 수 없다"

    def test_asking_again_after_an_answer(self, admin_client, cid, cert):
        """추가 질문 — 같은 건으로 다시 의뢰할 수 있다(앞선 회신은 남는다)."""
        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "첫 의뢰"})
        admin_client.post(f"{H}/{hid}/request/answer", json={"note": "첫 회신"})
        again = admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "추가 질문"})
        assert again.status_code == 200, again.text
        assert again.json()["state"] == "REQUESTED"
        assert again.json()["answer_note"] == "첫 회신", "앞선 회신은 지우지 않는다"

    def test_request_state_is_on_the_list_row(self, admin_client, cid, cert):
        hid = _make(admin_client, cid, title="목록에서 보이는 의뢰")["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "의뢰"})
        rows = admin_client.get(f"{H}?size=100").json()["items"]
        row = next(r for r in rows if r["id"] == hid)
        assert row["request_state"] == "REQUESTED"

    def test_request_shows_in_the_detail(self, admin_client, cid, cert):
        hid = _make(admin_client, cid)["id"]
        admin_client.post(f"{H}/{hid}/request", json={
            "to_user_ids": [cert["ids"][0]], "note": "의뢰 내용"})
        detail = admin_client.get(f"{H}/{hid}").json()
        assert detail["request"]["state_label"] == "의뢰함"
        assert detail["participant_counts"]["required"] >= 1


# --------------------------------------------------------------------------- 권한

class TestPermissions:
    def test_reader_cannot_change_participants(self, people, cid):
        admin, analyst = people["admin"], people["analyst"]
        hid = _make(admin, cid, title="남의 건")["id"]
        resp = analyst.put(f"{H}/{hid}/participants", json={"participants": []})
        assert resp.status_code in (403, 404), resp.text


@pytest.fixture
def people(users):
    clients = {"admin": _client("admin", ADMIN_PW), "analyst": _client("analyst1", ANALYST_PW),
               "manager": _client("manager1", MANAGER_PW)}
    yield {**clients, "ids": users}
    for c in clients.values():
        c.__exit__(None, None, None)
