"""반복 일정 규칙 — RFC 5545 RRULE 의 작은 부분집합(ASSUMPTIONS B-13).

받는 것: FREQ=DAILY|WEEKLY|MONTHLY, INTERVAL(1~99), BYDAY(WEEKLY 에서만 MO~SU),
COUNT(1~500) 또는 UNTIL(날짜). 그 밖의 키(BYSETPOS·BYHOUR 등)는 거절한다.
규칙이 복잡할수록 '다음 점검이 언제인지' 사람이 맞히기 어려워지고, 교대 근무 일정에는
이 정도면 충분하다(매일 점검, 매주 월·목 회의, 격주 금요일, 매월 1일 보고).

UNTIL 은 날짜만 받고 그 날 끝(KST)까지로 본다. dateutil 은 시간대가 있는 시작 시각과
함께 쓰려면 UNTIL 을 UTC 로 요구하므로 여기서 바꿔 넣는다.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from dateutil.rrule import rrulestr

from app.core.errors import ValidationFailed
from app.core.time import KST

FREQS = {"DAILY": "매일", "WEEKLY": "매주", "MONTHLY": "매월"}
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DAY_KO = dict(zip(DAYS, "월화수목금토일"))
MAX_COUNT = 500
#: 한 번에 펼치는 회차 상한 — 매일 반복을 1년 범위로 물어도 서버가 붙잡히지 않게.
MAX_OCCURRENCES = 400


def _fail(message: str) -> ValidationFailed:
    return ValidationFailed(f"반복 규칙: {message}", detail={"field": "recurrence_rule"})


def parse(rule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    body = rule.strip()
    if body.upper().startswith("RRULE:"):
        body = body[len("RRULE:"):]
    for chunk in filter(None, body.split(";")):
        if "=" not in chunk:
            raise _fail(f"'{chunk}' 는 KEY=VALUE 형식이 아닙니다.")
        key, value = chunk.split("=", 1)
        key, value = key.strip().upper(), value.strip().upper()
        if key in parts:
            raise _fail(f"{key} 가 두 번 나왔습니다.")
        parts[key] = value
    return parts


def normalize(rule: str | None) -> str | None:
    """검사하고 정해진 순서로 다시 쓴다. 비었으면 None(반복 없음)."""
    if rule is None or not rule.strip():
        return None
    parts = parse(rule)
    allowed = {"FREQ", "INTERVAL", "BYDAY", "COUNT", "UNTIL"}
    extra = sorted(set(parts) - allowed)
    if extra:
        raise _fail(f"{', '.join(extra)} 는 지원하지 않습니다(FREQ·INTERVAL·BYDAY·COUNT·UNTIL 만).")
    freq = parts.get("FREQ")
    if freq not in FREQS:
        raise _fail("FREQ 는 DAILY · WEEKLY · MONTHLY 중 하나여야 합니다.")
    out = [f"FREQ={freq}"]
    if "INTERVAL" in parts:
        if not parts["INTERVAL"].isdigit() or not 1 <= int(parts["INTERVAL"]) <= 99:
            raise _fail("INTERVAL 은 1~99 입니다.")
        if int(parts["INTERVAL"]) > 1:
            out.append(f"INTERVAL={int(parts['INTERVAL'])}")
    if "BYDAY" in parts:
        if freq != "WEEKLY":
            raise _fail("요일(BYDAY)은 매주 반복에서만 지정할 수 있습니다.")
        days = [d.strip() for d in parts["BYDAY"].split(",") if d.strip()]
        if not days or any(d not in DAYS for d in days):
            raise _fail("BYDAY 는 MO,TU,WE,TH,FR,SA,SU 중에서 고릅니다.")
        out.append("BYDAY=" + ",".join(sorted(set(days), key=DAYS.index)))
    if "COUNT" in parts and "UNTIL" in parts:
        raise _fail("COUNT 와 UNTIL 은 함께 쓸 수 없습니다.")
    if "COUNT" in parts:
        if not parts["COUNT"].isdigit() or not 1 <= int(parts["COUNT"]) <= MAX_COUNT:
            raise _fail(f"COUNT 는 1~{MAX_COUNT} 입니다.")
        out.append(f"COUNT={int(parts['COUNT'])}")
    if "UNTIL" in parts:
        out.append(f"UNTIL={_until_date(parts['UNTIL']).strftime('%Y%m%d')}")
    return ";".join(out)


def _until_date(value: str) -> date:
    digits = value[:8]
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise _fail("UNTIL 은 YYYYMMDD 날짜여야 합니다.") from None


def _for_dateutil(rule: str) -> str:
    parts = parse(rule)
    if "UNTIL" in parts:
        end = datetime.combine(_until_date(parts["UNTIL"]), time(23, 59, 59), tzinfo=KST)
        parts["UNTIL"] = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ";".join(f"{k}={v}" for k, v in parts.items())


def describe(rule: str | None) -> str | None:
    """'매주 월·수·금 · 10회' 처럼 사람이 읽는 말로."""
    if not rule:
        return None
    parts = parse(rule)
    interval = int(parts.get("INTERVAL", "1"))
    unit = {"DAILY": "일", "WEEKLY": "주", "MONTHLY": "개월"}[parts["FREQ"]]
    text = FREQS[parts["FREQ"]] if interval == 1 else f"{interval}{unit}마다"
    if "BYDAY" in parts:
        text += " " + "·".join(DAY_KO[d] for d in parts["BYDAY"].split(","))
    if "COUNT" in parts:
        text += f" · {parts['COUNT']}회"
    if "UNTIL" in parts:
        until = _until_date(parts["UNTIL"])
        text += f" · {until.isoformat()}까지"
    return text


def occurrences(rule: str | None, start: datetime, end: datetime,
                window_from: datetime, window_to: datetime) -> list[tuple[datetime, datetime]]:
    """[window_from, window_to) 와 겹치는 회차의 (시작, 끝). 반복이 없으면 원래 일정 하나."""
    duration = end - start
    if not rule:
        return [(start, end)] if start < window_to and end > window_from else []
    series = rrulestr(_for_dateutil(rule), dtstart=start.astimezone(KST))
    found: list[tuple[datetime, datetime]] = []
    # 창 앞에서 시작해 창 안까지 이어지는 회차도 잡으려면 길이만큼 앞에서부터 찾는다.
    for occ in series.xafter(window_from - duration, inc=True):
        if occ >= window_to or len(found) >= MAX_OCCURRENCES:
            break
        if occ + duration > window_from:
            found.append((occ, occ + duration))
    return found


def last_occurrence_end(rule: str | None, start: datetime, end: datetime) -> datetime | None:
    """끝이 있는 반복의 마지막 회차 끝. 끝이 없으면 None."""
    if not rule:
        return end
    parts = parse(rule)
    if "COUNT" not in parts and "UNTIL" not in parts:
        return None
    series = rrulestr(_for_dateutil(rule), dtstart=start.astimezone(KST))
    last = None
    for last in series:
        pass
    return (last + (end - start)) if last else end


def whole_days(start: datetime, days: int = 1) -> tuple[datetime, datetime]:
    """하루 종일 일정: 시작일 00:00 부터 days 일 뒤 00:00 까지(끝은 포함하지 않음)."""
    first = datetime.combine(start.astimezone(KST).date(), time.min, tzinfo=KST)
    return first, first + timedelta(days=max(1, days))
