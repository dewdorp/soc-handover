"""교대 인수인계 통합 테스트 — Cockpit · Basket · 전달 · 확인 · 재확인 · Carry Forward.

시나리오 E: 홍길동(주간) → 김철수(오후) → 김관리(야간)로 미완료가 이어서 넘어가는 동안
무엇을 언제 어느 버전으로 넘겼고 누가 어느 버전을 확인했는지가 끝까지 남는지 본다.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.main import app
from app.models.common import AuditLog, Notification
from app.models.handover import Handover
from app.models.reference import Company
from tests.conftest import ANALYST_PW, MANAGER_PW, ApiClient

P = "/api/v1/shift-handovers"
H = "/api/v1/handovers"


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    """세 명이 동시에 로그인한 상태. client 픽스처 하나를 돌려쓰면 로그인이 덮어써진다."""
    hong = _client("analyst1", ANALYST_PW)
    kim = _client("analyst2", ANALYST_PW)
    mgr = _client("manager1", MANAGER_PW)
    yield {"hong": hong, "kim": kim, "mgr": mgr, "ids": users}
    for c in (hong, kim, mgr):
        c.__exit__(None, None, None)


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _mk(client, cid, title, **over) -> int:
    resp = client.post(H, json={"company_id": cid, "title": title, "content": title,
                                "status_code": "IN_PROGRESS", **over})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _basket(client) -> dict:
    resp = client.get(f"{P}/basket")
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- Basket

class TestBasket:
    def test_basket_is_created_once(self, people):
        first = _basket(people["hong"])
        second = _basket(people["hong"])
        assert first["id"] == second["id"]
        assert first["status"] == "DRAFT" and first["items"] == []

    def test_add_remove_and_note(self, people, cid):
        hong = people["hong"]
        a, b = _mk(hong, cid, "A"), _mk(hong, cid, "B")
        added = hong.post(f"{P}/basket/items", json={"handover_ids": [a, b, a]}).json()
        assert added == {"added": [a, b], "skipped": []}
        again = hong.post(f"{P}/basket/items", json={"handover_ids": [a]}).json()
        assert again["skipped"] == [a], "같은 건을 두 번 담지 않는다"

        items = _basket(hong)["items"]
        first = next(i for i in items if i["handover_id"] == a)
        note = hong.patch(f"{P}/basket/items/{first['item_id']}", json={"item_note": "02시 재점검"})
        assert note.json()["item_note"] == "02시 재점검"
        assert hong.delete(f"{P}/basket/items/{first['item_id']}").status_code == 204
        assert [i["handover_id"] for i in _basket(hong)["items"]] == [b]

    def test_deleted_handover_is_skipped(self, people, cid):
        a = _mk(people["mgr"], cid, "지울 건")
        people["mgr"].request("DELETE", f"{H}/{a}", json={"reason": "중복"})
        out = people["hong"].post(f"{P}/basket/items", json={"handover_ids": [a]}).json()
        assert out["skipped"] == [a]

    def test_reorder(self, people, cid):
        hong = people["hong"]
        ids = [_mk(hong, cid, t) for t in ("1", "2", "3")]
        hong.post(f"{P}/basket/items", json={"handover_ids": ids})
        items = _basket(hong)["items"]
        reversed_ids = [i["item_id"] for i in reversed(items)]
        body = hong.patch(f"{P}/basket", json={"order": reversed_ids}).json()
        assert [i["item_id"] for i in body["items"]] == reversed_ids

    def test_cannot_touch_someone_elses_item(self, people, cid):
        a = _mk(people["hong"], cid, "A")
        people["hong"].post(f"{P}/basket/items", json={"handover_ids": [a]})
        item_id = _basket(people["hong"])["items"][0]["item_id"]
        assert people["kim"].delete(f"{P}/basket/items/{item_id}").status_code == 404


class TestSendValidation:
    def test_empty_basket_cannot_be_sent(self, people):
        resp = people["hong"].post(f"{P}/basket/send",
                                   json={"to_user_id": people["ids"]["analyst2"]["id"]})
        assert resp.status_code == 422

    def test_recipient_is_required(self, people, cid):
        people["hong"].post(f"{P}/basket/items", json={"handover_ids": [_mk(people["hong"], cid, "A")]})
        assert people["hong"].post(f"{P}/basket/send", json={}).status_code == 422

    def test_cannot_send_to_self(self, people, cid):
        people["hong"].post(f"{P}/basket/items", json={"handover_ids": [_mk(people["hong"], cid, "A")]})
        resp = people["hong"].post(f"{P}/basket/send",
                                   json={"to_user_id": people["ids"]["analyst"]["id"]})
        assert resp.status_code == 422


# --------------------------------------------------------------------------- 시나리오 E

class TestScenarioE:
    def test_handover_chain_across_three_shifts(self, people, cid, db):
        hong, kim, mgr = people["hong"], people["kim"], people["mgr"]
        ids = people["ids"]
        kim_id = ids["analyst2"]["id"]

        # 주간 홍길동: 세 건을 김철수에게 넘긴다(김철수가 담당이라 고칠 수 있다)
        a = _mk(hong, cid, "SSL VPN 이상징후", assignee_id=kim_id)
        b = _mk(hong, cid, "방화벽 정책 반영", assignee_id=kim_id)
        c = _mk(hong, cid, "로그 수집 지연", assignee_id=kim_id)
        hong.patch(f"{H}/{a}", json={"expected_version": 1, "remark": "v2 로 만든다"})
        hong.post(f"{P}/basket/items", json={"handover_ids": [a, b, c], "item_note": "확인 요망"})
        sent = hong.post(f"{P}/basket/send",
                         json={"to_user_id": kim_id, "summary_note": "주간 특이사항 없음"})
        assert sent.status_code == 200, sent.text
        s1 = sent.json()
        assert s1["status"] == "SENT" and s1["item_count"] == 3
        pinned = {i["handover_id"]: i["version_no_at_transfer"] for i in s1["items"]}
        assert pinned == {a: 2, b: 1, c: 1}, "전달 당시 버전을 항목마다 고정한다"

        # 김철수: 받은 알림 · 확인함
        assert kim.get("/api/v1/notifications/unread-count").json()["unread"] == 1
        inbox = {i["handover_id"]: i for i in kim.get(f"{P}/inbox").json()}
        assert set(inbox) == {a, b, c}
        assert inbox[a]["from_user"] == "홍길동" and inbox[a]["version_no_at_transfer"] == 2
        assert inbox[a]["state"] == "PENDING"
        assert kim.get("/api/v1/auth/me").json()["pending_ack_count"] == 3

        # 전달 뒤에 홍길동이 A 를 또 고친다 → 확인 전이라 PENDING 그대로, 전달 후 변경 표시
        hong.patch(f"{H}/{a}", json={"expected_version": 2, "title": "SSL VPN 이상징후(추가)"})
        detail = hong.get(f"{P}/{s1['id']}").json()
        item_a = next(i for i in detail["items"] if i["handover_id"] == a)
        assert item_a["changed_since_transfer"] is True
        assert (item_a["version_no_at_transfer"], item_a["current_version_no"]) == (2, 3)

        # 김철수: B 는 하나씩, C 는 일괄 확인
        assert kim.post(f"{H}/{b}/acknowledge", json={}).json()["acked_version_no"] == 1
        bulk = kim.post("/api/v1/acknowledgements/bulk", json={"handover_ids": [c]}).json()
        assert bulk["acknowledged"] == [c]

        # C 내용이 바뀌면 김철수의 확인은 재확인 필요로 + 알림
        hong.patch(f"{H}/{c}", json={"expected_version": 1, "content": "원인: 수집기 디스크 가득"})
        hong.patch(f"{H}/{c}", json={"expected_version": 2, "content": "원인: 디스크 + 권한"})
        inbox = {i["handover_id"]: i for i in kim.get(f"{P}/inbox").json()}
        assert inbox[c]["state"] == "REACK_REQUIRED"
        assert inbox[c]["stale_reason"] == ["content"]
        reack_notes = db.scalars(select(Notification).where(
            Notification.user_id == kim_id, Notification.type == "HANDOVER_REACK")).all()
        assert len(reack_notes) == 1, "같은 건의 연속 수정은 알림 하나로 갱신된다"

        # 아직 확인 안 된 게 있으면 닫을 수 없다
        blocked = hong.post(f"{P}/{s1['id']}/close")
        assert blocked.status_code == 409
        assert sorted(blocked.json()["detail"]["pending_handover_ids"]) == sorted([a, c])

        # 김철수가 B 를 끝낸다 → 다음 교대로 넘어갈 후보에서 빠져야 한다
        kim.patch(f"{H}/{b}", json={"expected_version": 1, "status_code": "DONE"})

        # 오후 김철수: Basket 을 열면 직전 교대에서 받은 미완료(A, C)가 자동으로 담긴다
        basket = _basket(kim)
        assert basket["auto_added"] == 2
        assert {i["handover_id"] for i in basket["items"]} == {a, c}
        assert all(i["is_carry_forward"] and i["carry_depth"] == 2 for i in basket["items"])
        assert basket["items"][0]["item_note"] == "확인 요망", "앞 교대의 메모도 따라온다"

        s2 = kim.post(f"{P}/basket/send", json={"to_user_id": ids["manager"]["id"]}).json()
        assert s2["status"] == "SENT"
        db.expire_all()
        assert db.get(Handover, a).carry_count == 2, "2교대째 인계 중"

        # 야간 김관리: 받은 것을 또 넘기면 3교대째
        basket3 = _basket(mgr)
        assert {i["carry_depth"] for i in basket3["items"]} == {3}

        # 김철수가 A·C 를 확인하면 첫 인계를 닫을 수 있다
        kim.post("/api/v1/acknowledgements/bulk", json={"handover_ids": [a, c]})
        closed = hong.post(f"{P}/{s1['id']}/close")
        assert closed.status_code == 200
        assert closed.json()["status"] == "CLOSED"
        assert closed.json()["acked_count"] == 3

        # 전달은 감사 기록으로 남는다
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "HANDOVER_TRANSFER")).all()
        assert len(logs) == 2
        assert logs[0].detail["count"] == 3


class TestCarryForwardSetting:
    def test_auto_carry_can_be_turned_off(self, people, cid, db):
        from app.services import settings_service

        hong, kim = people["hong"], people["kim"]
        a = _mk(hong, cid, "A")
        hong.post(f"{P}/basket/items", json={"handover_ids": [a]})
        hong.post(f"{P}/basket/send", json={"to_user_id": people["ids"]["analyst2"]["id"]})

        settings_service.set_value(db, "shift.carry_forward_auto", False)
        db.commit()
        basket = _basket(kim)
        assert basket["auto_added"] == 0 and basket["items"] == []
        assert basket["carry_candidates"] == 1, "자동으로 담지 않아도 후보는 알려준다"
        cands = kim.get(f"{P}/basket/carry-forward-candidates").json()
        assert [c["handover_id"] for c in cands] == [a]

        # 손으로 담아도 이어진 인계로 기록된다
        kim.post(f"{P}/basket/items", json={"handover_ids": [a]})
        item = _basket(kim)["items"][0]
        assert item["is_carry_forward"] and item["carry_depth"] == 2


# --------------------------------------------------------------------------- Cockpit

class TestCockpit:
    def test_six_areas(self, people, cid):
        body = people["hong"].get(f"{P}/cockpit").json()
        assert list(body["areas"]) == ["new_in_shift", "in_progress", "need_ack",
                                       "planned_next", "important", "overdue"]
        assert body["window"]["code"] in {"DAY", "SWING", "NIGHT"}

    def test_area_counts_equal_the_list(self, people, cid):
        """Cockpit 숫자와 '목록으로 보기'의 건수가 어긋나면 안 된다."""
        hong = people["hong"]
        _mk(hong, cid, "진행 건", is_important=True)
        _mk(hong, cid, "끝난 건", status_code="DONE", is_important=True)
        body = hong.get(f"{P}/cockpit").json()
        for key, area in body["areas"].items():
            listed = hong.post(f"{H}/search", json=area["request"]).json()
            assert listed["total"] == area["total"], key
        assert body["areas"]["important"]["total"] == 1, "끝난 중요 건은 빠진다"

    def test_new_in_shift_uses_the_shift_window(self, people, cid, db):
        from app.core.time import to_kst
        from app.models.reference import Shift
        from app.services.shift_service import current_window

        hid = _mk(people["hong"], cid, "방금 등록")
        created = to_kst(db.get(Handover, hid).created_at)
        window = current_window(db, created)
        shift_id = db.scalar(select(Shift.id).where(Shift.code == window.code))
        body = people["hong"].get(f"{P}/cockpit", params={
            "shift_date": window.shift_date.isoformat(), "shift_id": shift_id}).json()
        assert hid in [i["id"] for i in body["areas"]["new_in_shift"]["items"]]

    def test_basket_ids_are_reported(self, people, cid):
        hid = _mk(people["hong"], cid, "담은 건")
        people["hong"].post(f"{P}/basket/items", json={"handover_ids": [hid]})
        assert people["hong"].get(f"{P}/cockpit").json()["basket_handover_ids"] == [hid]


# --------------------------------------------------------------------------- 이력 / 알림 / 배너

class TestHistoryNotificationsBanner:
    def test_history_directions(self, people, cid):
        hong, kim = people["hong"], people["kim"]
        hong.post(f"{P}/basket/items", json={"handover_ids": [_mk(hong, cid, "A")]})
        hong.post(f"{P}/basket/send", json={"to_user_id": people["ids"]["analyst2"]["id"]})
        assert len(hong.get(P, params={"direction": "sent"}).json()) == 1
        assert hong.get(P, params={"direction": "received"}).json() == []
        received = kim.get(P, params={"direction": "received"}).json()
        assert received[0]["from_user"] == "홍길동"
        assert len(people["mgr"].get(P, params={"direction": "team"}).json()) == 1

    def test_draft_is_not_history(self, people, cid):
        hong = people["hong"]
        hong.post(f"{P}/basket/items", json={"handover_ids": [_mk(hong, cid, "A")]})
        draft_id = _basket(hong)["id"]
        assert hong.get(f"{P}/{draft_id}").status_code == 404
        assert hong.get(P).json() == []

    def test_notifications_read(self, people, cid):
        hong, kim = people["hong"], people["kim"]
        hong.post(f"{P}/basket/items", json={"handover_ids": [_mk(hong, cid, "A")]})
        hong.post(f"{P}/basket/send", json={"to_user_id": people["ids"]["analyst2"]["id"]})
        notes = kim.get("/api/v1/notifications").json()
        assert notes[0]["type"] == "HANDOVER_TRANSFER" and notes[0]["link_type"] == "SHIFT"
        assert hong.post(f"/api/v1/notifications/{notes[0]['id']}/read").status_code == 404, \
            "남의 알림은 읽음 처리할 수 없다"
        assert kim.post(f"/api/v1/notifications/{notes[0]['id']}/read").status_code == 204
        assert kim.get("/api/v1/notifications/unread-count").json()["unread"] == 0

    def test_banner_count_matches_list_after_delete(self, people, cid):
        """배너 숫자와 '확인필요' 목록 건수는 같은 기준이어야 한다(삭제된 건 제외)."""
        hong, kim, mgr = people["hong"], people["kim"], people["mgr"]
        a, b = _mk(hong, cid, "A"), _mk(hong, cid, "B")
        hong.post(f"{P}/basket/items", json={"handover_ids": [a, b]})
        hong.post(f"{P}/basket/send", json={"to_user_id": people["ids"]["analyst2"]["id"]})
        mgr.request("DELETE", f"{H}/{a}", json={"reason": "오등록"})
        banner = kim.get("/api/v1/auth/me").json()["pending_ack_count"]
        listed = kim.post(f"{H}/search", json={"quick": ["NEED_ACK"]}).json()["total"]
        assert banner == listed == 1
        assert [i["handover_id"] for i in kim.get(f"{P}/inbox").json()] == [b]


@pytest.mark.parametrize("hour,expected", [(9, "DAY"), (17, "SWING"), (3, "NIGHT")])
def test_current_window_boundaries(db, hour, expected):
    from app.core.time import KST
    from app.services.shift_service import current_window, next_window

    at = datetime(2026, 9, 16, hour, 0, tzinfo=KST)
    window = current_window(db, at)
    assert window.code == expected
    following = next_window(db, window)
    assert following.code == {"DAY": "SWING", "SWING": "NIGHT", "NIGHT": "DAY"}[expected]
    if expected == "SWING":
        assert following.shift_date.isoformat() == "2026-09-17", "자정을 넘는 다음 교대는 다음 날"
