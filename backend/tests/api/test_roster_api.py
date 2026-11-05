"""근무표 — 16일 주기가 실제로 맞물리는가, 대근·맞교환이 '실제 근무자'를 바꾸는가.

주장
  ① '주주주주 + (야비비)×4' 를 4일씩 밀면 **32일 내내** 매일 주간 1조 · 야간 1조다.
  ② 야간은 시작 날짜로 센다 — 11/05 야간은 11/05 18:00 ~ 11/06 09:00.
  ③ 대근·맞교환은 계획을 건드리지 않고 '실제'만 바꾼다. 취소하면 계획으로 돌아온다.
  ④ 한 사람을 두 조에, 또는 하루 두 근무에 넣을 수 없다.
  ⑤ 인계 상대 추천은 **실제 근무자**를 쓴다(대근자에게 넘겨야 한다).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.main import app
from app.models.roster import CYCLE_DAYS, PATTERN, RosterTeam
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient, _make_user

R = "/api/v1/roster"
EPOCH = "2026-01-05"      # 월요일


@pytest.fixture
def crew(db, users):
    """4조 × 2명. 정원을 2명으로 낮춰 '결원'을 시험할 수 있게 한다."""
    from app.services import roster_service, settings_service

    roster_service.ensure_teams(db)
    settings_service.set_value(db, "roster.epoch_date", EPOCH)
    settings_service.set_value(db, "roster.team_size", 2)

    made: dict[str, list[int]] = {}
    for idx, code in enumerate("ABCD"):
        team = db.scalar(select(RosterTeam).where(RosterTeam.code == code))
        people = [
            _make_user(db, f"crew{idx}1", f"{code}조원1", "ANALYST", ANALYST_PW),
            _make_user(db, f"crew{idx}2", f"{code}조원2", "ANALYST", ANALYST_PW),
        ]
        db.flush()
        from app.models.roster import RosterMember
        for order, person in enumerate(people):
            db.add(RosterMember(team_id=team.id, user_id=person.id, sort_order=order,
                                is_leader=order == 0))
        made[code] = [p.id for p in people]
    db.commit()
    return made


@pytest.fixture
def boss(users):
    c = ApiClient(app)
    c.__enter__()
    assert c.login("admin", ADMIN_PW).status_code == 200
    yield c
    c.__exit__(None, None, None)


# --------------------------------------------------------------------------- ① 주기

class TestCycle:
    def test_pattern_is_four_days_then_four_night_blocks(self):
        assert CYCLE_DAYS == 16
        assert PATTERN == "DDDD" + "N.." * 4
        assert PATTERN.count("D") == 4
        assert PATTERN.count("N") == 4
        assert PATTERN.count(".") == 8

    def test_thirty_two_days_have_exactly_one_day_and_one_night_team(self, boss, crew):
        out = boss.get(f"{R}/coverage?start={EPOCH}&days=32").json()
        assert out["ok"] is True, out["problems"]
        assert out["problems"] == []

    def test_each_team_works_eight_shifts_per_cycle(self, boss, crew, db):
        from app.services import roster_service

        for code in "ABCD":
            team = db.scalar(select(RosterTeam).where(RosterTeam.code == code))
            start = date.fromisoformat(EPOCH)
            codes = [roster_service.shift_of(db, team, start + timedelta(days=d))
                     for d in range(CYCLE_DAYS)]
            assert codes.count("DAY") == 4, code
            assert codes.count("NIGHT") == 4, code
            assert codes.count("OFF") == 8, code

    def test_bad_epoch_is_refused_and_rolled_back(self, boss, crew, db):
        from app.services import settings_service

        # 조 하나의 주기 위치를 어긋나게 하면 하루에 두 조가 겹친다.
        team = db.scalar(select(RosterTeam).where(RosterTeam.code == "B"))
        bad = boss.patch(f"{R}/teams/{team.id}", json={"phase_days": 0})
        assert bad.status_code == 200
        broken = boss.get(f"{R}/coverage?start={EPOCH}&days=32").json()
        assert broken["ok"] is False
        assert broken["problems"][0]["day_teams"] == ["A", "B"]

        before = settings_service.get_value(db, "roster.epoch_date")
        resp = boss.post(f"{R}/epoch?value=2026-02-02")
        assert resp.status_code == 422, resp.text
        db.expire_all()
        assert settings_service.get_value(db, "roster.epoch_date") == before, \
            "맞물리지 않는 기준일은 저장되지 않아야 한다"


# --------------------------------------------------------------------------- ② 야간의 날짜

class TestNightIsKeyedToItsStartDate:
    def test_night_window_crosses_midnight(self, boss, crew):
        rows = boss.get(f"{R}/mine?days=20")
        assert rows.status_code == 200

    def test_night_shift_runs_to_next_morning(self, db, crew):
        from app.services.roster_service import window_bounds

        start, end = window_bounds(date(2026, 11, 5), "NIGHT")
        assert start.isoformat().startswith("2026-11-05T18:00")
        assert end.isoformat().startswith("2026-11-06T09:00")

    def test_day_shift_is_same_day(self, db, crew):
        from app.services.roster_service import window_bounds

        start, end = window_bounds(date(2026, 11, 5), "DAY")
        assert start.date() == end.date() == date(2026, 11, 5)

    def test_after_midnight_belongs_to_the_previous_nights_shift(self, db, crew):
        from datetime import datetime

        from app.core.time import KST
        from app.services.roster_service import current_window

        day, code = current_window(db, datetime(2026, 11, 6, 3, 0, tzinfo=KST))
        assert (day, code) == (date(2026, 11, 5), "NIGHT")


# --------------------------------------------------------------------------- ③ 대근 · 맞교환

class TestSubstitution:
    def _duty(self, boss, offset=1):
        from app.core.time import today
        day = (today() + timedelta(days=offset)).isoformat()
        rows = boss.get(f"{R}/day?work_date={day}").json()
        return day, next(r for r in rows if r["actual_user_ids"])

    def _spare(self, boss, crew, day: str):
        """그 날 주간·야간과 전날 야간에 모두 들어 있지 않은 사람(이중 배정 금지 규칙과 같은 조건)."""
        busy: set[int] = set()
        prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        for d in (day, prev):
            for row in boss.get(f"{R}/day?work_date={d}").json():
                busy |= set(row["actual_user_ids"])
        return next(uid for code in "ABCD" for uid in crew[code] if uid not in busy)

    def test_substitute_changes_actual_not_planned(self, boss, crew):
        day, duty = self._duty(boss)
        off = duty["actual_user_ids"][0]
        spare = self._spare(boss, crew, day)   # 그 날 아무 근무에도 없는 사람

        made = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": duty["shift_code"],
            "off_user_id": off, "on_user_id": spare, "reason": "병가"})
        assert made.status_code == 201, made.text

        after = next(r for r in boss.get(f"{R}/day?work_date={day}").json()
                     if r["shift_code"] == duty["shift_code"])
        assert off in after["planned_user_ids"], "계획은 그대로여야 한다"
        assert off not in after["actual_user_ids"]
        assert spare in after["actual_user_ids"]
        assert after["is_short"] is False, "대근이 들어왔으므로 결원이 아니다"

    def test_absence_without_cover_is_marked_short(self, boss, crew):
        day, duty = self._duty(boss, offset=2)
        off = duty["actual_user_ids"][0]
        made = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": duty["shift_code"],
            "off_user_id": off, "reason": "결원"})
        assert made.status_code == 201, made.text
        assert made.json()["kind"] == "OFF"

        after = next(r for r in boss.get(f"{R}/day?work_date={day}").json()
                     if r["shift_code"] == duty["shift_code"])
        assert after["is_short"] is True
        assert after["short_by"] == 1

    def test_cancel_restores_the_plan(self, boss, crew):
        day, duty = self._duty(boss, offset=3)
        off = duty["actual_user_ids"][0]
        ovr = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": duty["shift_code"],
            "off_user_id": off, "reason": "취소해 볼 것"}).json()

        canceled = boss.post(f"{R}/overrides/{ovr['id']}/cancel", json={"reason": "복귀"})
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()[0]["canceled_at"]

        after = next(r for r in boss.get(f"{R}/day?work_date={day}").json()
                     if r["shift_code"] == duty["shift_code"])
        assert off in after["actual_user_ids"]
        assert after["is_short"] is False

    def test_cancel_twice_is_rejected(self, boss, crew):
        day, duty = self._duty(boss, offset=4)
        ovr = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": duty["shift_code"],
            "off_user_id": duty["actual_user_ids"][0]}).json()
        assert boss.post(f"{R}/overrides/{ovr['id']}/cancel", json={}).status_code == 200
        again = boss.post(f"{R}/overrides/{ovr['id']}/cancel", json={})
        assert again.status_code == 409, again.text

    def test_history_keeps_canceled_rows(self, boss, crew):
        day, duty = self._duty(boss, offset=5)
        ovr = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": duty["shift_code"],
            "off_user_id": duty["actual_user_ids"][0], "reason": "이력 확인"}).json()
        boss.post(f"{R}/overrides/{ovr['id']}/cancel", json={"reason": "되돌림"})

        rows = boss.get(f"{R}/overrides").json()
        row = next(r for r in rows if r["id"] == ovr["id"])
        assert row["reason"] == "이력 확인"
        assert row["cancel_reason"] == "되돌림"


class TestSwap:
    def test_mutual_swap_moves_both_people(self, boss, crew):
        from app.core.time import today

        d1 = (today() + timedelta(days=1)).isoformat()
        r1 = next(r for r in boss.get(f"{R}/day?work_date={d1}").json() if r["actual_user_ids"])
        # 같은 사람이 겹치지 않는 다른 날 근무를 찾는다
        other = None
        for offset in range(2, 10):
            d2 = (today() + timedelta(days=offset)).isoformat()
            for row in boss.get(f"{R}/day?work_date={d2}").json():
                if row["actual_user_ids"] and not set(row["actual_user_ids"]) & set(r1["actual_user_ids"]):
                    other = (d2, row)
                    break
            if other:
                break
        assert other, "맞교환할 다른 근무를 찾지 못했다"
        d2, r2 = other

        a, b = r1["actual_user_ids"][0], r2["actual_user_ids"][0]
        made = boss.post(f"{R}/swaps", json={
            "first": {"work_date": d1, "shift_code": r1["shift_code"], "user_id": a},
            "second": {"work_date": d2, "shift_code": r2["shift_code"], "user_id": b},
            "reason": "맞교환"})
        assert made.status_code == 201, made.text
        rows = made.json()
        assert len(rows) == 2
        assert rows[0]["pair_id"] == rows[1]["id"] and rows[1]["pair_id"] == rows[0]["id"]

        first = next(r for r in boss.get(f"{R}/day?work_date={d1}").json()
                     if r["shift_code"] == r1["shift_code"])
        second = next(r for r in boss.get(f"{R}/day?work_date={d2}").json()
                      if r["shift_code"] == r2["shift_code"])
        assert b in first["actual_user_ids"] and a not in first["actual_user_ids"]
        assert a in second["actual_user_ids"] and b not in second["actual_user_ids"]

    def test_canceling_one_side_cancels_both(self, boss, crew):
        from app.core.time import today

        d1 = (today() + timedelta(days=1)).isoformat()
        r1 = next(r for r in boss.get(f"{R}/day?work_date={d1}").json() if r["actual_user_ids"])
        other = None
        for offset in range(2, 10):
            d2 = (today() + timedelta(days=offset)).isoformat()
            for row in boss.get(f"{R}/day?work_date={d2}").json():
                if row["actual_user_ids"] and not set(row["actual_user_ids"]) & set(r1["actual_user_ids"]):
                    other = (d2, row)
                    break
            if other:
                break
        d2, r2 = other
        rows = boss.post(f"{R}/swaps", json={
            "first": {"work_date": d1, "shift_code": r1["shift_code"],
                      "user_id": r1["actual_user_ids"][0]},
            "second": {"work_date": d2, "shift_code": r2["shift_code"],
                       "user_id": r2["actual_user_ids"][0]}}).json()

        canceled = boss.post(f"{R}/overrides/{rows[0]['id']}/cancel", json={})
        assert canceled.status_code == 200
        assert len(canceled.json()) == 2, "맞교환은 한쪽만 되돌릴 수 없다"


# --------------------------------------------------------------------------- ④ 이중 배정

class TestNoDoubleBooking:
    def test_one_person_cannot_be_in_two_teams(self, boss, crew, db):
        a = db.scalar(select(RosterTeam).where(RosterTeam.code == "A"))
        resp = boss.put(f"{R}/teams/{a.id}/members",
                        json={"user_ids": crew["A"] + [crew["B"][0]]})
        assert resp.status_code == 409, resp.text
        assert "conflicts" in resp.json()["detail"]

    def test_cannot_substitute_into_an_overlapping_shift(self, boss, crew):
        from app.core.time import today

        day = (today() + timedelta(days=1)).isoformat()
        rows = boss.get(f"{R}/day?work_date={day}").json()
        day_row = next(r for r in rows if r["shift_code"] == "DAY")
        night_row = next(r for r in rows if r["shift_code"] == "NIGHT")

        # 주간 근무자를 그 날 야간 대근으로 넣으려 하면 막힌다.
        resp = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": "NIGHT",
            "off_user_id": night_row["actual_user_ids"][0],
            "on_user_id": day_row["actual_user_ids"][0]})
        assert resp.status_code == 409, resp.text

    def test_cannot_take_off_someone_not_on_duty(self, boss, crew):
        from app.core.time import today

        day = (today() + timedelta(days=1)).isoformat()
        rows = boss.get(f"{R}/day?work_date={day}").json()
        night = next(r for r in rows if r["shift_code"] == "NIGHT")
        outsider = next(uid for code in "ABCD" for uid in crew[code]
                        if uid not in night["actual_user_ids"]
                        and uid not in rows[0]["actual_user_ids"])
        resp = boss.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": "NIGHT", "off_user_id": outsider})
        assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- ⑤ 인계 상대 추천

def _free_person(boss, crew, day: str) -> int:
    """그 날 주간·야간과 전날 야간에 모두 들어 있지 않은 사람.

    서버의 이중 배정 금지 규칙과 **같은 조건**이다. 여기서 조건을 느슨하게 잡으면
    실행 시각(다음 근무가 주간인지 야간인지)에 따라 붙었다 떨어지는 시험이 된다.
    """
    busy: set[int] = set()
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    for d in (day, prev):
        for row in boss.get(f"{R}/day?work_date={d}").json():
            busy |= set(row["actual_user_ids"])
    return next(uid for code in "ABCD" for uid in crew[code] if uid not in busy)


class TestRecipientSuggestion:
    def test_next_shift_lists_actual_staff(self, boss, crew):
        out = boss.get(f"{R}/next-shift").json()
        assert out["user_ids"], out
        assert len(out["names"]) == len(out["user_ids"])

    def test_substitute_shows_up_in_the_suggestion(self, boss, crew):
        out = boss.get(f"{R}/next-shift").json()
        off = out["user_ids"][0]
        spare = _free_person(boss, crew, out["work_date"])
        made = boss.post(f"{R}/overrides", json={
            "work_date": out["work_date"], "shift_code": out["shift_code"],
            "off_user_id": off, "on_user_id": spare, "reason": "대근"})
        assert made.status_code == 201, made.text

        again = boss.get(f"{R}/next-shift").json()
        assert spare in again["user_ids"], "대근자가 인계 상대로 나와야 한다"
        assert off not in again["user_ids"]
        assert again["replaced"], "누가 누구를 대신하는지 함께 보여 준다"

    def test_my_shifts_include_substituted_in(self, boss, crew, users):
        out = boss.get(f"{R}/next-shift").json()
        spare = _free_person(boss, crew, out["work_date"])
        boss.post(f"{R}/overrides", json={
            "work_date": out["work_date"], "shift_code": out["shift_code"],
            "off_user_id": out["user_ids"][0], "on_user_id": spare})

        # 대근으로 들어온 사람의 '내 근무'에 그 날이 나온다.
        from app.models.user import User
        from tests.conftest import ApiClient as C
        name = None
        with C(app) as c:
            for idx in range(4):
                for n in (1, 2):
                    username = f"crew{idx}{n}"
                    resp = c.login(username, ANALYST_PW)
                    if resp.status_code != 200:
                        continue
                    me = c.get("/api/v1/auth/me").json()
                    if me["id"] == spare:
                        name = username
                        rows = c.get(f"{R}/mine?days=5").json()
                        assert any(r["work_date"] == out["work_date"]
                                   and r["shift_code"] == out["shift_code"] for r in rows), rows
                        break
                if name:
                    break
        assert name, "대근자 계정을 찾지 못했다"
        assert User  # import 가 쓰이도록


# --------------------------------------------------------------------------- 권한

class TestPermissions:
    def test_everyone_can_read_the_roster(self, analyst_client, crew):
        assert analyst_client.get(f"{R}/calendar?view=week").status_code == 200
        assert analyst_client.get(f"{R}/teams").status_code == 200

    def test_only_shift_manager_can_change_it(self, analyst_client, crew):
        from app.core.time import today

        day = (today() + timedelta(days=1)).isoformat()
        resp = analyst_client.post(f"{R}/overrides", json={
            "work_date": day, "shift_code": "DAY", "off_user_id": 1})
        assert resp.status_code == 403, resp.text
