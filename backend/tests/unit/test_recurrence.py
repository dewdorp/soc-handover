"""반복 일정 규칙(부분집합) — 검사 · 설명 · 기간 안 회차 펼치기."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.errors import ValidationFailed
from app.core.time import KST
from app.services import recurrence as r


def at(month, day, hour=0, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


class TestNormalize:
    def test_rewrites_in_fixed_order(self):
        assert r.normalize("rrule:freq=weekly;byday=fr,mo,we;count=10") == "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10"
        assert r.normalize("FREQ=DAILY;INTERVAL=1") == "FREQ=DAILY", "INTERVAL=1 은 적지 않는다"
        assert r.normalize("  ") is None and r.normalize(None) is None

    @pytest.mark.parametrize("rule", [
        "FREQ=YEARLY", "FREQ=DAILY;BYDAY=MO", "FREQ=WEEKLY;BYHOUR=9", "FREQ=DAILY;COUNT=3;UNTIL=20261231",
        "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;COUNT=501", "FREQ=WEEKLY;BYDAY=XX", "FREQ=DAILY;UNTIL=2026-12",
        "junk", "FREQ=DAILY;FREQ=WEEKLY",
    ])
    def test_rejects_outside_subset(self, rule):
        with pytest.raises(ValidationFailed):
            r.normalize(rule)


def test_describe():
    assert r.describe("FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10") == "매주 월·수·금 · 10회"
    assert r.describe("FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;UNTIL=20261231") == "2주마다 금 · 2026-12-31까지"
    assert r.describe("FREQ=MONTHLY") == "매월"
    assert r.describe(None) is None


class TestOccurrences:
    def test_weekly_until_includes_last_day(self):
        start = at(9, 14, 9)                                   # 월요일 09:00
        occ = r.occurrences("FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261001", start, start + timedelta(hours=1),
                            at(9, 1), at(11, 1))
        assert [a.strftime("%m-%d") for a, _ in occ] == ["09-14", "09-17", "09-21", "09-24", "09-28", "10-01"]

    def test_occurrence_straddling_window_start_is_included(self):
        start = at(9, 18, 23)                                  # 23:00~01:00
        occ = r.occurrences("FREQ=DAILY;COUNT=3", start, start + timedelta(hours=2), at(9, 19), at(9, 20))
        assert [(a.day, b.day) for a, b in occ] == [(18, 19), (19, 20)]

    def test_single_event(self):
        start = at(9, 19, 10)
        assert r.occurrences(None, start, start + timedelta(hours=1), at(9, 19), at(9, 20)) == [
            (start, start + timedelta(hours=1))]
        assert r.occurrences(None, start, start + timedelta(hours=1), at(9, 20), at(9, 21)) == []

    def test_expansion_is_capped(self):
        start = at(1, 1, 9)
        occ = r.occurrences("FREQ=DAILY", start, start + timedelta(hours=1), at(1, 1), datetime(2028, 1, 1, tzinfo=KST))
        assert len(occ) == r.MAX_OCCURRENCES

    def test_series_end(self):
        start = at(9, 18, 23)
        assert r.last_occurrence_end("FREQ=DAILY;COUNT=3", start, start + timedelta(hours=2)) == at(9, 21, 1)
        assert r.last_occurrence_end("FREQ=DAILY", start, start + timedelta(hours=2)) is None
