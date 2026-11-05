"""④ 교대 마감 점검 · 내 일정 · 일정 알림.

주장
  ① 마감 점검의 숫자는 **그 목록과 같은 조건**으로 센다. 누르면 같은 것이 열린다.
  ② 다음 근무가 결원이면 마감 점검이 그것을 집어 준다(인계가 빌 자리를 미리 본다).
  ③ '내 일정'은 반복 일정이 목록을 먹지 않도록 한 일정당 앞의 몇 회차만 준다.
  ④ 일정 알림은 사람마다 따로다. 끄면 다시 오지 않고, 한 회차에 한 번만 간다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import KST, now, today
from app.main import app
from app.models.reference import Company
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient

S = "/api/v1/shift-handovers"
H = "/api/v1/handovers"
SC = "/api/v1"


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _client(username: str, password: str) -> ApiClient:
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


@pytest.fixture
def boss(users):
    c = _client("admin", ADMIN_PW)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def crewless(db, users):
    """근무조는 있으나 사람은 넣지 않은 상태(설치 직후). 근무 결원 줄은 '배정 없음'이 된다."""
    from app.services import roster_service
    roster_service.ensure_teams(db)
    db.commit()
    return True


@pytest.fixture
def crew(db, users):
    """4조 × 2명, 정원 2명 — 결원을 만들어 볼 수 있게."""
    from app.models.roster import RosterMember, RosterTeam
    from app.services import roster_service, settings_service
    from tests.conftest import _make_user

    roster_service.ensure_teams(db)
    settings_service.set_value(db, "roster.epoch_date", "2026-01-05")
    settings_service.set_value(db, "roster.team_size", 2)
    made: dict[str, list[int]] = {}
    for idx, code in enumerate("ABCD"):
        team = db.scalar(select(RosterTeam).where(RosterTeam.code == code))
        people_ = [_make_user(db, f"shift{idx}1", f"{code}1", "ANALYST", ANALYST_PW),
                   _make_user(db, f"shift{idx}2", f"{code}2", "ANALYST", ANALYST_PW)]
        db.flush()
        for order, person in enumerate(people_):
            db.add(RosterMember(team_id=team.id, user_id=person.id, sort_order=order))
        made[code] = [p.id for p in people_]
    db.commit()
    return made


# --------------------------------------------------------------------------- ① ② 마감 점검

class TestClosingCheck:
    def test_all_clear_on_a_quiet_shift(self, analyst_client, crewless):
        out = analyst_client.get(f"{S}/closing-check").json()
        keys = [r["key"] for r in out["rows"]]
        assert keys == ["unacked", "basket", "my_open", "overdue", "next_shift"]
        assert all("url" in r for r in out["rows"])

    def test_basket_row_counts_what_is_not_sent_yet(self, analyst_client, cid, crewless):
        made = analyst_client.post(H, json={"company_id": cid, "title": "담아만 둔 것",
                                            "content": "x"})
        assert made.status_code == 201, made.text
        add = analyst_client.post(f"{S}/basket/items",
                                  json={"handover_ids": [made.json()["id"]]})
        assert add.status_code == 200, add.text

        out = analyst_client.get(f"{S}/closing-check").json()
        row = next(r for r in out["rows"] if r["key"] == "basket")
        assert row["count"] == 1
        assert row["tone"] == "check"
        assert out["all_clear"] is False

        basket = analyst_client.get(f"{S}/basket").json()
        assert len(basket["items"]) == row["count"], "점검 숫자와 바구니 목록이 같아야 한다"

    def test_unacked_row_matches_the_inbox_list(self, people, cid, crewless):
        admin, analyst, ids = people["admin"], people["analyst"], people["ids"]
        made = admin.post(H, json={"company_id": cid, "title": "확인 필요", "content": "x"})
        hid = made.json()["id"]
        admin.post(f"{S}/basket/items", json={"handover_ids": [hid]})
        sent = admin.post(f"{S}/basket/send",
                          json={"to_user_ids": [ids["analyst"]["id"]], "confirm_window": True})
        assert sent.status_code in (200, 201), sent.text

        out = analyst.get(f"{S}/closing-check").json()
        row = next(r for r in out["rows"] if r["key"] == "unacked")
        inbox = analyst.get(f"{S}/inbox").json()
        assert row["count"] == len(inbox) == 1

    def test_next_shift_shortage_is_surfaced(self, boss, crew):
        nxt = boss.get("/api/v1/roster/next-shift").json()
        before = boss.get(f"{S}/closing-check").json()
        assert next(r for r in before["rows"] if r["key"] == "next_shift")["count"] == 0

        made = boss.post("/api/v1/roster/overrides", json={
            "work_date": nxt["work_date"], "shift_code": nxt["shift_code"],
            "off_user_id": nxt["user_ids"][0], "reason": "결원"})
        assert made.status_code == 201, made.text

        after = boss.get(f"{S}/closing-check").json()
        row = next(r for r in after["rows"] if r["key"] == "next_shift")
        assert row["count"] == 1
        assert row["tone"] == "urgent"
        assert after["next_shift"]["is_short"] is True


# --------------------------------------------------------------------------- ③ 내 일정

class TestMySchedules:
    def test_recurring_series_is_capped(self, analyst_client):
        start = datetime.combine(today(), datetime.min.time(), tzinfo=KST) + timedelta(days=1, hours=10)
        made = analyst_client.post(f"{SC}/schedules", json={
            "title": "매일 점검", "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "recurrence_rule": "FREQ=DAILY"})
        assert made.status_code == 201, made.text

        rows = analyst_client.get(f"{SC}/schedules/mine?days=7&per_series=3").json()
        mine = [r for r in rows if r["title"] == "매일 점검"]
        assert len(mine) == 3, "반복 일정이 7줄을 다 먹지 않아야 한다"
        assert mine[0]["occurrence_no"] == 1
        assert mine[0]["more_occurrences"] >= 1, "보여 주지 않은 회차 수를 알려 준다"

    def test_only_my_schedules(self, people):
        admin, analyst = people["admin"], people["analyst"]
        start = (now() + timedelta(days=1)).isoformat()
        admin.post(f"{SC}/schedules", json={"title": "관리자 일정", "start_at": start})
        rows = analyst.get(f"{SC}/schedules/mine").json()
        assert not any(r["title"] == "관리자 일정" for r in rows)


# --------------------------------------------------------------------------- ④ 일정 알림

class TestScheduleReminder:
    def _schedule(self, client, minutes_ahead: int = 20) -> dict:
        start = now() + timedelta(minutes=minutes_ahead)
        resp = client.post(f"{SC}/schedules", json={
            "title": "알림 확인용", "start_at": start.isoformat()})
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_reminder_is_per_person(self, people):
        admin, analyst = people["admin"], people["analyst"]
        s = self._schedule(admin)
        assert admin.put(f"{SC}/schedules/{s['id']}/reminder",
                         json={"minutes_before": 30}).json()["minutes_before"] == 30
        # 다른 사람에게는 설정이 없다
        assert analyst.get(f"{SC}/schedules/mine").status_code == 200
        from app.services import schedule_service
        assert admin.get(f"{SC}/schedules/{s['id']}").status_code == 200
        assert schedule_service.REMINDER_CHOICES == (None, 0, 10, 30)

    def test_off_removes_the_setting(self, admin_client):
        s = self._schedule(admin_client)
        admin_client.put(f"{SC}/schedules/{s['id']}/reminder", json={"minutes_before": 10})
        off = admin_client.put(f"{SC}/schedules/{s['id']}/reminder", json={"minutes_before": None})
        assert off.json()["minutes_before"] is None

    def test_job_sends_once_per_occurrence(self, admin_client, db, users):
        from app.jobs import reminders

        s = self._schedule(admin_client, minutes_ahead=20)
        admin_client.put(f"{SC}/schedules/{s['id']}/reminder", json={"minutes_before": 30})
        db.expire_all()

        sent = reminders.run_schedule_reminders(db)
        db.commit()
        assert sent == 1, "30분 전 알림이므로 지금 보내야 한다"

        again = reminders.run_schedule_reminders(db)
        db.commit()
        assert again == 0, "같은 회차에 두 번 보내지 않는다"

        notes = admin_client.get("/api/v1/notifications").json()
        mine = [n for n in notes if n["type"] == "SCHEDULE_REMINDER"]
        assert len(mine) == 1
        assert "알림 확인용" in mine[0]["title"]

    def test_too_early_is_not_sent(self, admin_client, db):
        s = self._schedule(admin_client, minutes_ahead=60 * 10)   # 10시간 뒤
        admin_client.put(f"{SC}/schedules/{s['id']}/reminder", json={"minutes_before": 10})
        db.expire_all()
        from app.jobs import reminders
        assert reminders.run_schedule_reminders(db) == 0

    def test_long_past_is_not_sent(self, admin_client, db):
        start = now() - timedelta(hours=6)
        made = admin_client.post(f"{SC}/schedules", json={
            "title": "지난 일정", "start_at": start.isoformat()})
        admin_client.put(f"{SC}/schedules/{made.json()['id']}/reminder",
                         json={"minutes_before": 0})
        db.expire_all()
        from app.jobs import reminders
        assert reminders.run_schedule_reminders(db) == 0, \
            "6시간 지난 일정을 지금 알리면 지금 일로 착각한다"
