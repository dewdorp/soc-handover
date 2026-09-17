"""시간/교대 계산. 전 시스템 KST 기준(ASSUMPTIONS A-05)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    """현재 시각(KST aware)."""
    return datetime.now(KST)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return now().date()


def to_kst(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


def start_of_day(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=KST)


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=KST)


def week_start(d: date | None = None) -> date:
    """월요일 시작."""
    d = d or today()
    return d - timedelta(days=d.weekday())


def month_start(d: date | None = None) -> date:
    d = d or today()
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + months, 12)
    return date(y, m + 1, 1)


class DateRange(NamedTuple):
    start: date
    end: date


def quick_range(token: str, base: date | None = None) -> DateRange:
    """날짜 Quick Filter 토큰 → 날짜 범위(양끝 포함). 사양서 §11."""
    d = base or today()
    t = token.upper()
    if t == "TODAY":
        return DateRange(d, d)
    if t == "YESTERDAY":
        return DateRange(d - timedelta(days=1), d - timedelta(days=1))
    if t == "THIS_WEEK":
        s = week_start(d)
        return DateRange(s, s + timedelta(days=6))
    if t == "LAST_WEEK":
        s = week_start(d) - timedelta(days=7)
        return DateRange(s, s + timedelta(days=6))
    if t == "THIS_MONTH":
        s = month_start(d)
        return DateRange(s, add_months(s, 1) - timedelta(days=1))
    if t == "LAST_MONTH":
        s = add_months(month_start(d), -1)
        return DateRange(s, month_start(d) - timedelta(days=1))
    if t == "LAST_7_DAYS":
        return DateRange(d - timedelta(days=6), d)
    if t == "LAST_30_DAYS":
        return DateRange(d - timedelta(days=29), d)
    if t == "THIS_YEAR":
        return DateRange(date(d.year, 1, 1), date(d.year, 12, 31))
    if t == "LAST_YEAR":
        return DateRange(date(d.year - 1, 1, 1), date(d.year - 1, 12, 31))
    raise ValueError(f"알 수 없는 날짜 범위 토큰: {token}")


QUICK_RANGE_TOKENS = (
    "TODAY", "YESTERDAY", "THIS_WEEK", "LAST_WEEK", "THIS_MONTH", "LAST_MONTH",
    "LAST_7_DAYS", "LAST_30_DAYS", "THIS_YEAR", "LAST_YEAR",
)


class ShiftWindow(NamedTuple):
    code: str
    shift_date: date
    start_at: datetime
    end_at: datetime


def resolve_shift(defs: list[dict], at: datetime | None = None) -> ShiftWindow | None:
    """교대 정의 목록에서 지정 시각이 속한 근무를 찾는다.

    defs 항목: {"code": "NIGHT", "start_time": "00:00", "end_time": "08:00",
                "crosses_midnight": false}
    야간처럼 자정을 넘는 근무는 시작일 기준으로 shift_date 를 잡는다.
    """
    at = at or now()
    cur = at.timetz().replace(tzinfo=None)
    for d in defs:
        s = time.fromisoformat(d["start_time"])
        e = time.fromisoformat(d["end_time"])
        crosses = bool(d.get("crosses_midnight")) or e <= s
        if not crosses:
            if s <= cur < e:
                return ShiftWindow(
                    d["code"], at.date(),
                    datetime.combine(at.date(), s, tzinfo=KST),
                    datetime.combine(at.date(), e, tzinfo=KST),
                )
        else:
            if cur >= s:  # 당일 저녁 시작
                sd = at.date()
                return ShiftWindow(
                    d["code"], sd,
                    datetime.combine(sd, s, tzinfo=KST),
                    datetime.combine(sd + timedelta(days=1), e, tzinfo=KST),
                )
            if cur < e:  # 자정 넘어 이어지는 근무 → 전일이 shift_date
                sd = at.date() - timedelta(days=1)
                return ShiftWindow(
                    d["code"], sd,
                    datetime.combine(sd, s, tzinfo=KST),
                    datetime.combine(at.date(), e, tzinfo=KST),
                )
    return None
