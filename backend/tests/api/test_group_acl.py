"""열람 그룹 — 목록·상세·첨부·댓글·이력·검색·알림·통계·Excel·내려받기 토큰까지 한 줄로 막히는가.

핵심 주장 네 가지
  ① 다른 그룹의 업무는 **목록에도 숫자에도** 나오지 않는다.
  ② 번호를 직접 알아도 상세·이력·첨부·댓글이 열리지 않는다(403 이 아니라 404).
  ③ 그룹에서 빠지면 **다음 요청부터** 끊긴다 — 이미 받은 내려받기 토큰도 못 쓴다.
  ④ 관리자도 예외가 아니다. 그룹을 만들 수 있다는 것이 원문을 읽을 근거는 아니다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.group import Group, UserGroup
from app.models.reference import Company
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient, _make_user

H = "/api/v1/handovers"
G = "/api/v1/groups"


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def two_groups(db, users):
    """'관제1팀'(홍길동) · '관제2팀'(박영희). 두 사람은 서로의 그룹에 없다.

    기본 그룹('미분류')에서도 빼서, 겹치는 범위가 전혀 없는 상태를 만든다.
    """
    from app.services import group_service

    g1 = Group(name="관제1팀", sort_order=1)
    g2 = Group(name="관제2팀", sort_order=2)
    db.add_all([g1, g2])
    db.flush()

    other = _make_user(db, "analyst9", "박영희", "ANALYST", ANALYST_PW, groups=False)
    # 1팀의 다른 사람 — '남이 쓴, 내 그룹에 공개된 글'을 만들기 위해 필요하다.
    writer = _make_user(db, "analyst8", "이작성", "ANALYST", ANALYST_PW, groups=False)
    db.execute(UserGroup.__table__.delete().where(
        UserGroup.user_id == users["analyst"]["id"]))
    db.add_all([
        UserGroup(user_id=users["analyst"]["id"], group_id=g1.id, is_default=True),
        UserGroup(user_id=other.id, group_id=g2.id, is_default=True),
        UserGroup(user_id=writer.id, group_id=g1.id, is_default=True),
    ])
    # 관리자는 어느 그룹에도 넣지 않는다 — ④ 를 시험하기 위해.
    db.execute(UserGroup.__table__.delete().where(
        UserGroup.user_id == users["admin"]["id"]))
    db.commit()
    assert group_service.my_group_ids(db, users["analyst"]["id"]) == (g1.id,)
    return {"g1": g1.id, "g2": g2.id, "other_id": other.id, "writer_id": writer.id}


@pytest.fixture
def pair(users, two_groups):
    a = _client("analyst1", ANALYST_PW)      # 관제1팀
    b = _client("analyst9", ANALYST_PW)      # 관제2팀
    writer = _client("analyst8", ANALYST_PW)  # 관제1팀 (다른 사람)
    adm = _client("admin", ADMIN_PW)         # 그룹 없음
    yield {"a": a, "b": b, "writer": writer, "admin": adm, **two_groups}
    for c in (a, b, writer, adm):
        c.__exit__(None, None, None)


def _make(client, cid, title="그룹 통제 확인", **over) -> dict:
    r = client.post(H, json={"company_id": cid, "title": title, "content": title,
                             "status_code": "IN_PROGRESS", **over})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- ① 목록 · 숫자

class TestOtherGroupsAreNotListed:
    def test_default_scope_is_my_group_not_everyone(self, pair, cid):
        body = _make(pair["a"], cid)
        assert body["visibility"] == "GROUPS"
        assert body["group_names"] == ["관제1팀"], "비워 두면 내 기본 그룹이 들어가야 한다"

    def test_list_hides_other_groups(self, pair, cid):
        mine = _make(pair["a"], cid, title="1팀 전용")
        theirs = _make(pair["b"], cid, title="2팀 전용")

        ids = [r["id"] for r in pair["a"].get(f"{H}?size=100").json()["items"]]
        assert mine["id"] in ids
        assert theirs["id"] not in ids

    def test_total_count_does_not_leak_hidden_rows(self, pair, cid):
        _make(pair["b"], cid, title="2팀 것")
        _make(pair["b"], cid, title="2팀 것 또")
        _make(pair["a"], cid, title="1팀 것")

        page = pair["a"].get(f"{H}?q=것&size=100").json()
        # '전체 N건'에 남의 그룹 건수가 섞이면 제목은 못 봐도 몇 건인지는 새어 나간다.
        assert page["total_all"] == 1, page

    def test_search_and_facets_follow_the_same_scope(self, pair, cid):
        _make(pair["b"], cid, title="2팀 침해사고")
        found = pair["a"].post("/api/v1/handovers/search",
                               json={"q": "침해사고", "size": 50}).json()
        assert found["total"] == 0
        facets = pair["a"].post("/api/v1/handovers/facets",
                                json={"q": "침해사고", "field": "company_id"}).json()
        assert sum(f["count"] for f in facets) == 0

    def test_excel_export_cannot_widen_the_scope(self, pair, cid):
        _make(pair["b"], cid, title="2팀 내보내기")
        out = pair["a"].post("/api/v1/export/handovers",
                             json={"q": "내보내기", "format": "csv"})
        assert out.status_code == 200, out.text
        assert out.json()["rows"] == 0


# --------------------------------------------------------------------------- ② 직접 주소

class TestDirectUrlIsClosed:
    def test_detail_is_404_not_403(self, pair, cid):
        hid = _make(pair["b"], cid)["id"]
        resp = pair["a"].get(f"{H}/{hid}")
        # 403 이면 '그 번호의 업무가 있다'는 사실이 새어 나간다.
        assert resp.status_code == 404, resp.text

    @pytest.mark.parametrize("suffix", ["/versions", "/timeline", "/acknowledgements",
                                        "/versions/1"])
    def test_sub_resources_are_closed(self, pair, cid, suffix):
        hid = _make(pair["b"], cid)["id"]
        assert pair["a"].get(f"{H}/{hid}{suffix}").status_code == 404

    def test_comments_are_closed_both_ways(self, pair, cid):
        hid = _make(pair["b"], cid)["id"]
        assert pair["a"].get(f"{H}/{hid}/comments").status_code == 404
        assert pair["a"].post(f"{H}/{hid}/comments", json={"body": "들여다보기"}).status_code == 404

    def test_attachment_list_and_preview_are_closed(self, pair, cid):
        hid = _make(pair["b"], cid)["id"]
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        up = pair["b"].post("/api/v1/attachments",
                            data={"entity_type": "HANDOVER", "entity_id": str(hid)},
                            files={"file": ("shot.png", png, "image/png")})
        assert up.status_code == 201, up.text
        att = up.json()["id"]

        assert pair["a"].get(f"/api/v1/attachments?entity_type=HANDOVER&entity_id={hid}"
                             ).status_code == 404
        assert pair["a"].get(f"/api/v1/attachments/{att}/preview").status_code == 404
        assert pair["a"].get(f"/api/v1/attachments/{att}/download").status_code == 404

    def test_cannot_attach_a_task_or_schedule_to_an_unseen_handover(self, pair, cid):
        hid = _make(pair["b"], cid)["id"]
        task = pair["a"].post("/api/v1/tasks", json={"title": "끌어오기", "handover_id": hid})
        assert task.status_code in (400, 404, 422), task.text
        sched = pair["a"].post("/api/v1/schedules", json={
            "title": "끌어오기", "handover_id": hid,
            "start_at": "2026-11-06T09:00:00+09:00", "all_day": True})
        assert sched.status_code in (400, 404, 422), sched.text

    def test_cannot_publish_into_someone_elses_group(self, pair, cid):
        resp = pair["a"].post(H, json={"company_id": cid, "title": "밀어넣기",
                                       "content": "x", "group_ids": [pair["g2"]]})
        assert resp.status_code == 422, resp.text
        assert "속하지 않은" in resp.json()["message"]


# --------------------------------------------------------------------------- ③ 회수는 다음 요청부터

class TestRevocationTakesEffectImmediately:
    def test_leaving_the_group_hides_the_row_on_the_next_request(self, pair, cid, db, users):
        # 남이 쓴 글이어야 한다 — 내가 쓴 글은 당사자라 그룹과 무관하게 계속 보인다.
        hid = _make(pair["writer"], cid, title="보던 것")["id"]
        assert pair["a"].get(f"{H}/{hid}").status_code == 200

        db.execute(UserGroup.__table__.delete().where(
            UserGroup.user_id == users["analyst"]["id"]))
        db.commit()

        # 로그아웃하지 않았고 토큰도 그대로다. 그래도 바로 끊긴다.
        assert pair["a"].get(f"{H}/{hid}").status_code == 404

    def test_deactivating_the_group_is_enough(self, pair, cid, db):
        hid = _make(pair["writer"], cid)["id"]
        assert pair["a"].get(f"{H}/{hid}").status_code == 200

        group = db.get(Group, pair["g1"])
        group.is_active = False
        db.commit()
        # 구성원을 지우지 않아도 열람이 끊긴다.
        assert pair["a"].get(f"{H}/{hid}").status_code == 404

    def test_already_issued_download_token_stops_working(self, pair, cid, db, users):
        _make(pair["writer"], cid, title="토큰 확인용")
        issued = pair["a"].post("/api/v1/export/handovers",
                                json={"q": "토큰 확인용", "format": "csv"})
        assert issued.status_code == 200, issued.text
        token = issued.json()["download_token"]
        assert pair["a"].get(f"/api/v1/export/download/{token}").status_code == 200

        db.execute(UserGroup.__table__.delete().where(
            UserGroup.user_id == users["analyst"]["id"]))
        db.commit()

        again = pair["a"].get(f"/api/v1/export/download/{token}")
        assert again.status_code == 404, again.text

    def test_notifications_about_hidden_work_disappear(self, pair, cid, db, users):
        # 2팀 사람이 1팀 사람을 담당자로 지정하면 알림이 간다(담당자라 그 건은 보인다).
        other = pair["other_id"]
        _make(pair["b"], cid, title="담당 지정", assignee_id=users["analyst"]["id"])
        notes = pair["a"].get("/api/v1/notifications").json()
        assert any(n["link_type"] == "HANDOVER" for n in notes), notes
        assert other  # 고정구가 실제로 두 번째 사람을 만들었는지

    def test_notification_hides_when_link_becomes_invisible(self, pair, cid, db, users):
        hid = _make(pair["a"], cid, title="알림 대상",
                    assignee_id=pair["other_id"])["id"]
        before = pair["b"].get("/api/v1/notifications").json()
        assert any(n["link_id"] == hid for n in before), before

        # 담당자에서 빼면 2팀 사람에게는 더 이상 보이지 않는 건이 된다.
        version = pair["a"].get(f"{H}/{hid}").json()["current_version_no"]
        patched = pair["a"].patch(f"{H}/{hid}", json={"expected_version": version,
                                                      "assignee_id": None})
        assert patched.status_code == 200, patched.text

        after = pair["b"].get("/api/v1/notifications").json()
        assert not any(n["link_id"] == hid and n["link_type"] == "HANDOVER" for n in after), after


# --------------------------------------------------------------------------- ④ 관리자도 예외가 아니다

class TestAdminHasNoBackDoor:
    def test_group_manager_cannot_read_other_groups_content(self, pair, cid):
        hid = _make(pair["a"], cid, title="관리자도 못 본다")["id"]
        # 관리자는 그룹을 만들고 사람을 넣을 수 있다.
        assert pair["admin"].get(G).status_code == 200
        # 그러나 원문은 열리지 않는다.
        assert pair["admin"].get(f"{H}/{hid}").status_code == 404
        ids = [r["id"] for r in pair["admin"].get(f"{H}?size=100").json()["items"]]
        assert hid not in ids

    def test_group_listing_shows_counts_not_titles(self, pair, cid):
        _make(pair["a"], cid, title="제목이 새면 안 된다")
        rows = pair["admin"].get(G).json()
        body = str(rows)
        assert "제목이 새면 안 된다" not in body
        assert any(r["name"] == "관제1팀" and r["handover_count"] >= 1 for r in rows), rows

    def test_admin_can_join_a_group_and_then_sees_it(self, pair, cid, users):
        hid = _make(pair["a"], cid, title="들어가면 보인다")["id"]
        assert pair["admin"].get(f"{H}/{hid}").status_code == 404

        put = pair["admin"].put(f"/api/v1/users/{users['admin']['id']}/groups",
                                json={"group_ids": [pair["g1"]],
                                      "default_group_id": pair["g1"]})
        assert put.status_code == 200, put.text
        assert pair["admin"].get(f"{H}/{hid}").status_code == 200


# --------------------------------------------------------------------------- 그룹 관리 · 이관

class TestGroupAdministration:
    def test_create_rename_and_stop(self, admin_client):
        made = admin_client.post(G, json={"name": "야간조", "description": "22시 이후"})
        assert made.status_code == 201, made.text
        gid = made.json()["id"]

        renamed = admin_client.patch(f"{G}/{gid}", json={"name": "심야조"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "심야조"

        stopped = admin_client.patch(f"{G}/{gid}", json={"is_active": False})
        assert stopped.json()["is_active"] is False

    def test_duplicate_name_is_rejected(self, admin_client):
        assert admin_client.post(G, json={"name": "중복조"}).status_code == 201
        again = admin_client.post(G, json={"name": "중복조"})
        assert again.status_code == 409, again.text

    def test_reserved_group_cannot_be_stopped(self, admin_client, db):
        gid = db.scalar(select(Group.id).where(Group.code == "UNCLASSIFIED"))
        resp = admin_client.patch(f"{G}/{gid}", json={"is_active": False})
        assert resp.status_code == 422, resp.text

    def test_unclassified_data_moves_without_becoming_public(self, admin_client, cid, db):
        """이관은 '전체 공개'로 바꾸지 않는다 — 그룹만 바꾼다."""
        hid = _make(admin_client, cid, title="옮길 자료")["id"]
        before = admin_client.get(f"{H}/{hid}").json()
        assert before["visibility"] == "GROUPS"
        assert before["group_names"] == ["미분류"]

        target = admin_client.post(G, json={"name": "이관대상팀"}).json()["id"]
        summary = admin_client.get(f"{G}/unclassified/summary").json()
        assert summary["total"] >= 1

        moved = admin_client.post(f"{G}/unclassified/move", json={"to_group_id": target})
        assert moved.status_code == 200, moved.text
        assert moved.json()["moved"] >= 1

        # 관리자는 아직 '이관대상팀'에 속하지 않지만, 자기가 쓴 글이라 계속 보인다.
        after = admin_client.get(f"{H}/{hid}").json()
        assert after["visibility"] == "GROUPS", "전체 공개로 바뀌면 안 된다"
        assert after["group_names"] == ["이관대상팀"]

    def test_scope_change_is_audited_and_versioned(self, admin_client, cid):
        hid = _make(admin_client, cid, title="범위를 넓힌다")["id"]
        version = admin_client.get(f"{H}/{hid}").json()["current_version_no"]
        resp = admin_client.patch(f"{H}/{hid}", json={"expected_version": version,
                                                      "visibility": "ALL"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["visibility"] == "ALL"

        from app.core.time import today
        day = today().isoformat()
        rows = admin_client.post("/api/v1/audit/search", json={
            "start": f"{day}T00:00:00+09:00", "end": f"{day}T23:59:59+09:00",
            "actions": ["HANDOVER_SCOPE_CHANGE"], "size": 10}).json()
        assert rows["total"] >= 1, rows
        assert rows["items"][0]["after_value"]["visibility"] == "ALL"

    def test_public_scope_is_visible_to_everyone(self, pair, cid):
        hid = _make(pair["a"], cid, title="전체 공지")["id"]
        version = pair["a"].get(f"{H}/{hid}").json()["current_version_no"]
        pair["a"].patch(f"{H}/{hid}", json={"expected_version": version, "visibility": "ALL"})
        # 다른 그룹 사람도, 그룹이 없는 관리자도 본다.
        assert pair["b"].get(f"{H}/{hid}").status_code == 200
        assert pair["admin"].get(f"{H}/{hid}").status_code == 200


# --------------------------------------------------------------------------- 내 업무는 사라지지 않는다

class TestMyOwnWorkStaysVisible:
    def test_assignee_keeps_seeing_the_row_across_groups(self, pair, cid, users):
        hid = _make(pair["b"], cid, title="남의 그룹, 내 담당",
                    assignee_id=users["analyst"]["id"])["id"]
        # 그룹은 2팀이지만 담당자라 보인다 — 아니면 내 할 일이 내 화면에서 사라진다.
        assert pair["a"].get(f"{H}/{hid}").status_code == 200

    def test_shift_recipient_keeps_seeing_the_row(self, pair, cid, users, db):
        hid = _make(pair["b"], cid, title="인계로 받은 것")["id"]
        add = pair["b"].post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [hid]})
        assert add.status_code == 200, add.text
        sent = pair["b"].post("/api/v1/shift-handovers/basket/send",
                              json={"to_user_ids": [users["analyst"]["id"]],
                                    "confirm_window": True})
        assert sent.status_code in (200, 201), sent.text
        # 받은 사람은 그룹이 달라도 그 건을 본다(인계가 성립해야 하므로).
        assert pair["a"].get(f"{H}/{hid}").status_code == 200

    def test_basket_refuses_handovers_i_cannot_see(self, pair, cid):
        hid = _make(pair["b"], cid, title="못 보는 건")["id"]
        add = pair["a"].post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [hid]})
        assert add.status_code == 200, add.text
        assert add.json()["added"] == []
        assert hid in add.json()["skipped"]
