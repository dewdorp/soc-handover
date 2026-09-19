"""일정 · 달력 통합 테스트 (FR-E).

시나리오: 김관리가 인수인계에서 점검 일정을 잡아 홍길동에게 맡긴다(제목·관계사 자동, 알림)
→ 달력에 일정 · 할일 마감 · 인수인계 수행일이 겹쳐 보인다 → 홍길동이 끌어서 하루 미룬다
(길이 유지, 감사 via=drag) → 옛 화면에서 또 옮기면 409 → 인수인계 타임라인에 일정이 남는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import KST, today
from app.main import app
from app.models.common import AuditLog
from app.models.reference import Company
from tests.conftest import ANALYST_PW, MANAGER_PW, ApiClient

S = "/api/v1/schedules"
C = "/api/v1/calendar"
H = "/api/v1/handovers"


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    hong = _client("analyst1", ANALYST_PW)
    kim = _client("analyst2", ANALYST_PW)
    mgr = _client("manager1", MANAGER_PW)
    yield {"hong": hong, "kim": kim, "mgr": mgr, "ids": users}
    for c in (hong, kim, mgr):
        c.__exit__(None, None, None)


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _sched(client, **body) -> dict:
    body.setdefault("title", "일정")
    body.setdefault("start_at", "2026-10-05T10:00:00+09:00")
    resp = client.post(S, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _kst(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M")


# --------------------------------------------------------------------------- 시나리오

class TestScenario:
    def test_inspection_from_handover_moved_on_calendar(self, people, cid, db):
        hong, mgr = people["hong"], people["mgr"]
        hong_id = people["ids"]["analyst"]["id"]
        h = mgr.post(H, json={"company_id": cid, "title": "방화벽 정기 점검", "content": "분기 점검",
                              "status_code": "IN_PROGRESS", "work_date": "2026-10-06"}).json()["id"]
        task = mgr.post("/api/v1/tasks", json={"title": "점검 결과 보고", "due_date": "2026-10-07",
                                               "assignee_id": hong_id}).json()

        s = _sched(mgr, title=None, handover_id=h, owner_id=hong_id, event_type="INSPECTION",
                   start_at="2026-10-05T14:00:00+09:00", end_at="2026-10-05T16:00:00+09:00")
        assert s["title"] == "방화벽 정기 점검" and s["company"]["id"] == cid, "비운 제목·관계사는 인수인계에서"
        assert (s["owner"]["id"], s["creator"]["username"], s["version_no"]) == (hong_id, "manager1", 1)
        assert s["can_edit"] is True
        notes = hong.get("/api/v1/notifications").json()
        assert [(n["type"], n["link_type"], n["link_id"]) for n in notes
                if n["type"] == "SCHEDULE_ASSIGNED"] == [("SCHEDULE_ASSIGNED", "SCHEDULE", s["id"])]

        # 달력: 일정 · 할일 마감 · 인수인계 수행일
        cal = hong.get(C, params={"start": "2026-10-01T00:00:00+09:00", "end": "2026-11-01T00:00:00+09:00"}).json()
        kinds = {(e["kind"], e["id"]) for e in cal["events"]}
        assert {("SCHEDULE", s["id"]), ("TASK", task["id"]), ("HANDOVER", h)} <= kinds
        ev = next(e for e in cal["events"] if e["kind"] == "SCHEDULE")
        assert ev["can_move"] and not ev["all_day"] and ev["event_type"] == "INSPECTION"

        # 홍길동이 끌어서 하루 미룬다 — 길이(2시간) 유지
        moved = hong.patch(f"{S}/{s['id']}/move", json={"expected_version": 1, "start_at": "2026-10-06T14:00:00+09:00"})
        assert moved.status_code == 200, moved.text
        assert (_kst(moved.json()["start_at"]), _kst(moved.json()["end_at"])) == ("10-06 14:00", "10-06 16:00")

        # 옛 화면(v1)에서 또 옮기면 막는다
        stale = mgr.patch(f"{S}/{s['id']}/move", json={"expected_version": 1, "start_at": "2026-10-07T09:00:00+09:00"})
        assert stale.status_code == 409 and stale.json()["detail"]["current_version_no"] == 2

        logs = db.scalars(select(AuditLog).where(AuditLog.resource_type == "SCHEDULE").order_by(AuditLog.id)).all()
        assert [l.action for l in logs] == ["CALENDAR_CREATE", "CALENDAR_UPDATE"]
        assert logs[1].after_value["via"] == "drag"
        assert logs[1].before_value["start_at"].startswith("2026-10-05T14:00")

        # 인수인계 쪽: 일정 수 · 목록 · 타임라인
        assert mgr.get(f"{H}/{h}").json()["schedule_count"] == 1
        assert [x["id"] for x in mgr.get(f"{H}/{h}/schedules").json()] == [s["id"]]
        assert any(e["kind"] == "SCHEDULE" for e in mgr.get(f"{H}/{h}/timeline").json())


# --------------------------------------------------------------------------- 시각 규칙

class TestTimes:
    def test_default_length_and_naive_is_kst(self, people):
        s = _sched(people["hong"], start_at="2026-10-05T10:00:00")
        assert (_kst(s["start_at"]), _kst(s["end_at"])) == ("10-05 10:00", "10-05 11:00")

    def test_all_day_snaps_to_midnight(self, people):
        s = _sched(people["hong"], is_all_day=True, start_at="2026-10-05T15:00:00+09:00",
                   end_at="2026-10-06T10:00:00+09:00")
        assert (_kst(s["start_at"]), _kst(s["end_at"])) == ("10-05 00:00", "10-07 00:00"), "끝나는 날까지 포함"

    @pytest.mark.parametrize("end", ["2026-10-05T10:00:00+09:00", "2026-10-05T09:00:00+09:00",
                                     "2026-11-10T10:00:00+09:00"])
    def test_bad_end(self, people, end):
        resp = people["hong"].post(S, json={"title": "x", "start_at": "2026-10-05T10:00:00+09:00", "end_at": end})
        assert resp.status_code == 422

    def test_title_required_without_link(self, people):
        assert people["hong"].post(S, json={"start_at": "2026-10-05T10:00:00+09:00"}).status_code == 422

    def test_changing_start_keeps_length(self, people):
        s = _sched(people["hong"], end_at="2026-10-05T12:30:00+09:00")
        out = people["hong"].patch(f"{S}/{s['id']}", json={"expected_version": 1,
                                                          "start_at": "2026-10-08T09:00:00+09:00"}).json()
        assert (_kst(out["start_at"]), _kst(out["end_at"])) == ("10-08 09:00", "10-08 11:30")

    def test_all_day_move_keeps_days(self, people):
        s = _sched(people["hong"], is_all_day=True, start_at="2026-10-05", end_at="2026-10-07")
        out = people["hong"].patch(f"{S}/{s['id']}/move", json={"expected_version": 1,
                                                               "start_at": "2026-10-12T00:00:00+09:00"}).json()
        assert (_kst(out["start_at"]), _kst(out["end_at"])) == ("10-12 00:00", "10-14 00:00")


# --------------------------------------------------------------------------- 반복

class TestRecurring:
    def test_expanded_on_calendar_and_not_draggable(self, people):
        s = _sched(people["hong"], title="주간 회의", event_type="MEETING",
                   start_at="2026-10-05T09:00:00+09:00", recurrence_rule="FREQ=WEEKLY;BYDAY=MO,TH;COUNT=4")
        assert s["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=MO,TH;COUNT=4"
        assert s["recurrence_text"] == "매주 월·목 · 4회"
        assert _kst(s["series_end"]) == "10-15 10:00"
        cal = people["hong"].get(C, params={"start": "2026-10-01T00:00:00+09:00", "end": "2026-11-01T00:00:00+09:00",
                                            "layers": "schedule"}).json()
        occ = [e for e in cal["events"] if e["id"] == s["id"]]
        assert [_kst(e["start"]) for e in occ] == ["10-05 09:00", "10-08 09:00", "10-12 09:00", "10-15 09:00"]
        assert len({e["key"] for e in occ}) == 4, "회차마다 키가 다르다"
        assert all(e["recurring"] and not e["can_move"] for e in occ)

    def test_invalid_rule_rejected(self, people):
        resp = people["hong"].post(S, json={"title": "x", "start_at": "2026-10-05T09:00:00+09:00",
                                            "recurrence_rule": "FREQ=YEARLY"})
        assert resp.status_code == 422 and resp.json()["detail"]["field"] == "recurrence_rule"


# --------------------------------------------------------------------------- 권한 · 삭제

class TestPermissions:
    def test_owner_creator_or_manager(self, people):
        s = _sched(people["hong"], title="홍길동 일정")
        body = {"expected_version": 1, "title": "남이 고침"}
        assert people["kim"].patch(f"{S}/{s['id']}", json=body).status_code == 403
        assert people["kim"].patch(f"{S}/{s['id']}/move", json={"expected_version": 1, "start_at": "2026-10-06T10:00:00+09:00"}).status_code == 403
        assert people["mgr"].patch(f"{S}/{s['id']}", json=body).status_code == 200
        cal = people["kim"].get(C, params={"start": "2026-10-01T00:00:00+09:00", "end": "2026-11-01T00:00:00+09:00"}).json()
        assert not next(e for e in cal["events"] if e["id"] == s["id"])["can_move"]

    def test_delete(self, people, db):
        s = _sched(people["hong"])
        assert people["kim"].delete(f"{S}/{s['id']}").status_code == 403
        assert people["hong"].request("DELETE", f"{S}/{s['id']}", json={"reason": "취소됨"}).status_code == 204
        assert people["hong"].get(f"{S}/{s['id']}").status_code == 404
        log = db.scalar(select(AuditLog).where(AuditLog.action == "CALENDAR_DELETE"))
        assert log.after_value == {"reason": "취소됨"}


# --------------------------------------------------------------------------- 달력 · 내 업무 · 검색

class TestCalendar:
    def test_mine_and_range_limits(self, people):
        _sched(people["hong"], title="내 일정")
        _sched(people["kim"], title="남의 일정")
        params = {"start": "2026-10-01T00:00:00+09:00", "end": "2026-11-01T00:00:00+09:00"}
        titles = {e["title"] for e in people["hong"].get(C, params={**params, "mine": "true"}).json()["events"]}
        assert titles == {"내 일정"}
        assert people["hong"].get(C, params={"start": "2026-01-01T00:00:00+09:00",
                                            "end": "2026-06-01T00:00:00+09:00"}).status_code == 422
        assert people["hong"].get(C, params={**params, "layers": "nope"}).status_code == 422


class TestMyWork:
    def test_schedule_today_and_series_once(self, people):
        hong = people["hong"]
        t0 = today()
        at_ten = datetime.combine(t0, datetime.min.time(), tzinfo=KST) + timedelta(hours=23, minutes=30)
        once = _sched(hong, title="오늘 점검", start_at=at_ten.isoformat(), end_at=(at_ten + timedelta(minutes=20)).isoformat())
        daily = _sched(hong, title="매일 로그 확인", start_at=(at_ten - timedelta(days=3)).isoformat(),
                       end_at=(at_ten - timedelta(days=3) + timedelta(minutes=20)).isoformat(), recurrence_rule="FREQ=DAILY")
        body = hong.get("/api/v1/my-work", params={"bucket": "today", "source": "schedule"}).json()
        ids = [(i["kind"], i["id"]) for i in body["items"]]
        assert ids.count(("SCHEDULE", daily["id"])) == 1, "매일 반복도 한 줄"
        assert ("SCHEDULE", once["id"]) in ids
        assert body["counts"]["today"] == 2

    def test_global_search(self, people):
        _sched(people["hong"], title="분기 DR 훈련")
        body = people["hong"].post("/api/v1/search/global", json={"q": "DR 훈련"}).json()
        assert body["totals"]["schedule"] == 1 and body["hits"][0]["type"] == "schedule"
