"""core 유틸 단위 테스트: 비밀번호 정책 · 토큰 · 날짜/교대 계산."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core.security import (create_access_token, csrf_matches, decode_access_token,
                               hash_password, hash_token, new_refresh_token,
                               validate_password_policy, verify_password)
from app.core.time import KST, quick_range, resolve_shift, week_start


class TestPassword:
    def test_hash_and_verify(self):
        h = hash_password("Corr3ct!Horse#Batt")
        assert h != "Corr3ct!Horse#Batt"
        assert verify_password("Corr3ct!Horse#Batt", h)
        assert not verify_password("wrong", h)

    def test_verify_none_hash(self):
        assert not verify_password("x", None)

    @pytest.mark.parametrize("pw,expect_ok", [
        ("Short1!", False),                 # 12자 미만
        ("alllowercaseonly", False),        # 조합 부족
        ("Password1234!", True),
        ("한글Password12!", True),           # 한글 포함 비밀번호도 허용
    ])
    def test_policy(self, pw, expect_ok):
        assert (validate_password_policy(pw) == []) is expect_ok

    def test_policy_rejects_username(self):
        problems = validate_password_policy("hongildong!A1234", "hongildong")
        assert any("계정명" in p for p in problems)


class TestTokens:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id=7, username="hong", role="ANALYST")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "7"
        assert payload["rol"] == "ANALYST"

    def test_expired_token_rejected(self):
        token = create_access_token(user_id=1, username="a", role="ADMIN", minutes=-1)
        assert decode_access_token(token) is None

    def test_tampered_token_rejected(self):
        token = create_access_token(user_id=1, username="a", role="ADMIN")
        assert decode_access_token(token[:-2] + "xx") is None

    def test_refresh_token_stored_as_hash(self):
        raw, hashed = new_refresh_token()
        assert raw != hashed
        assert hash_token(raw) == hashed
        assert len(hashed) == 64

    def test_csrf_compare(self):
        assert csrf_matches("abc", "abc")
        assert not csrf_matches("abc", "abd")
        assert not csrf_matches(None, "abc")
        assert not csrf_matches("abc", None)


class TestTimeUtils:
    def test_week_start_is_monday(self):
        assert week_start(date(2026, 9, 16)) == date(2026, 9, 14)  # 수 → 월
        assert week_start(date(2026, 9, 14)) == date(2026, 9, 14)

    @pytest.mark.parametrize("token,expected", [
        ("TODAY", (date(2026, 9, 16), date(2026, 9, 16))),
        ("YESTERDAY", (date(2026, 9, 15), date(2026, 9, 15))),
        ("THIS_WEEK", (date(2026, 9, 14), date(2026, 9, 20))),
        ("LAST_WEEK", (date(2026, 9, 7), date(2026, 9, 13))),
        ("THIS_MONTH", (date(2026, 9, 1), date(2026, 9, 30))),
        ("LAST_MONTH", (date(2026, 8, 1), date(2026, 8, 31))),
        ("LAST_7_DAYS", (date(2026, 9, 10), date(2026, 9, 16))),
        ("LAST_30_DAYS", (date(2026, 8, 18), date(2026, 9, 16))),
        ("THIS_YEAR", (date(2026, 1, 1), date(2026, 12, 31))),
        ("LAST_YEAR", (date(2025, 1, 1), date(2025, 12, 31))),
    ])
    def test_quick_ranges(self, token, expected):
        r = quick_range(token, base=date(2026, 9, 16))
        assert (r.start, r.end) == expected

    def test_unknown_token(self):
        with pytest.raises(ValueError):
            quick_range("NEXT_CENTURY")


SHIFT_DEFS = [
    {"code": "DAY", "start_time": "08:00", "end_time": "16:00"},
    {"code": "SWING", "start_time": "16:00", "end_time": "00:00", "crosses_midnight": True},
    {"code": "NIGHT", "start_time": "00:00", "end_time": "08:00"},
]


class TestShiftResolution:
    def test_day_shift(self):
        w = resolve_shift(SHIFT_DEFS, datetime(2026, 9, 16, 9, 30, tzinfo=KST))
        assert w.code == "DAY"
        assert w.shift_date == date(2026, 9, 16)

    def test_swing_shift(self):
        w = resolve_shift(SHIFT_DEFS, datetime(2026, 9, 16, 22, 0, tzinfo=KST))
        assert w.code == "SWING"
        assert w.shift_date == date(2026, 9, 16)
        assert w.end_at == datetime(2026, 9, 17, 0, 0, tzinfo=KST)

    def test_night_shift(self):
        w = resolve_shift(SHIFT_DEFS, datetime(2026, 9, 17, 3, 0, tzinfo=KST))
        assert w.code == "NIGHT"
        assert w.shift_date == date(2026, 9, 17)

    def test_shift_crossing_midnight_keeps_start_date(self):
        """자정을 넘겨 이어지는 근무는 '시작일' 기준으로 집계되어야 교대 통계가 어긋나지 않는다."""
        defs = [{"code": "LONG_NIGHT", "start_time": "22:00", "end_time": "06:00",
                 "crosses_midnight": True}]
        w = resolve_shift(defs, datetime(2026, 9, 17, 2, 0, tzinfo=KST))
        assert w.code == "LONG_NIGHT"
        assert w.shift_date == date(2026, 9, 16)
        assert w.start_at == datetime(2026, 9, 16, 22, 0, tzinfo=KST)

    def test_boundary_start_inclusive(self):
        w = resolve_shift(SHIFT_DEFS, datetime(2026, 9, 16, 8, 0, tzinfo=KST))
        assert w.code == "DAY"

    def test_boundary_end_exclusive(self):
        w = resolve_shift(SHIFT_DEFS, datetime(2026, 9, 16, 16, 0, tzinfo=KST))
        assert w.code == "SWING"
