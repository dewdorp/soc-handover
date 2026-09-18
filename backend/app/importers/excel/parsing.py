"""셀 값 해석 — 관대하게 읽되, 추정한 것은 추정했다고 표시한다 (ASSUMPTIONS D-03).

Excel 원본은 사람이 손으로 쓴 것이라 같은 날짜도 '2026-09-16', '2026.9.16',
'9/16', '9월 16일(화)', 엑셀 일련번호 45916 처럼 제각각이다. 전부 받아들이되,
연도를 시트 이름에서 빌려온 경우에는 date_inferred 를 남겨 나중에 의심할 수 있게 한다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

_EXCEL_EPOCH = date(1899, 12, 30)
#: 1954 ~ 2119 사이의 일련번호만 날짜로 본다. 그 밖의 숫자는 날짜가 아닐 가능성이 크다.
_SERIAL_RANGE = (20_000, 80_000)

_PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")          # (화), [오전] 같은 꼬리
_TIME_TAIL = re.compile(r"(?:\s+|T)\d{1,2}:\d{2}(:\d{2})?.*$")  # 뒤에 붙은 시각

_FULL = [
    re.compile(r"^(?P<y>\d{4})\s*[-./년]\s*(?P<m>\d{1,2})\s*[-./월]\s*(?P<d>\d{1,2})\s*일?$"),
    re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$"),
    re.compile(r"^(?P<y>\d{2})\s*[-.]\s*(?P<m>\d{1,2})\s*[-.]\s*(?P<d>\d{1,2})$"),
]
_NO_YEAR = [
    re.compile(r"^(?P<m>\d{1,2})\s*[/.-]\s*(?P<d>\d{1,2})$"),
    re.compile(r"^(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?$"),
]

#: 4자리 연도는 단독으로, 2자리는 '년'이 붙을 때만 연도로 본다. 'Sheet12' 를 2012년으로
#: 읽으면 날짜가 전부 틀어진다.
_SHEET_YEAR = re.compile(r"(?<!\d)(?:(?P<y4>(?:19|20)\d{2})(?!\d)|(?P<y2>\d{2})\s*년)")


class ParsedDate(NamedTuple):
    value: date | None
    inferred: bool = False
    error: str | None = None


def year_from_sheet(sheet_name: str | None) -> int | None:
    """'2024', '2024년', '24년 인수인계' → 2024."""
    if not sheet_name:
        return None
    match = _SHEET_YEAR.search(sheet_name)
    if not match:
        return None
    if match.group("y4"):
        return int(match.group("y4"))
    return 2000 + int(match.group("y2"))


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(value: Any, *, fallback_year: int | None = None) -> ParsedDate:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ParsedDate(None)
    if isinstance(value, datetime):
        return ParsedDate(value.date())
    if isinstance(value, date):
        return ParsedDate(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        serial = int(value)
        if _SERIAL_RANGE[0] <= serial <= _SERIAL_RANGE[1]:
            return ParsedDate(_EXCEL_EPOCH + timedelta(days=serial))
        if 19000101 <= serial <= 21001231:  # 20260916 처럼 숫자로 들어간 경우
            return parse_date(str(serial), fallback_year=fallback_year)
        return ParsedDate(None, error=f"날짜로 해석할 수 없는 숫자입니다: {value}")

    # staging raw 에는 datetime 이 ISO 문자열('2025-03-10T00:00:00')로 보존된다.
    # 이걸 못 읽으면 정상 날짜가 '해석 실패'가 되고, 수행일이 있는 행은 조용히 수행일로
    # 대체돼 **틀린 등록일**이 들어간다. ISO 부터 먼저 시도한다.
    raw_text = str(value).strip()
    try:
        return ParsedDate(datetime.fromisoformat(raw_text).date())
    except ValueError:
        pass

    text = _PARENS.sub("", raw_text).strip()
    text = _TIME_TAIL.sub("", text).strip()
    text = text.rstrip(".").strip()

    for pattern in _FULL:
        match = pattern.match(text)
        if match:
            y = int(match.group("y"))
            y = y + 2000 if y < 100 else y
            parsed = _make(y, int(match.group("m")), int(match.group("d")))
            return ParsedDate(parsed) if parsed else ParsedDate(
                None, error=f"존재하지 않는 날짜입니다: {value}")

    for pattern in _NO_YEAR:
        match = pattern.match(text)
        if match:
            if fallback_year is None:
                return ParsedDate(None, error=f"연도를 알 수 없는 날짜입니다: {value}")
            parsed = _make(fallback_year, int(match.group("m")), int(match.group("d")))
            return ParsedDate(parsed, inferred=True) if parsed else ParsedDate(
                None, error=f"존재하지 않는 날짜입니다: {value}")

    return ParsedDate(None, error=f"날짜 형식을 알 수 없습니다: {value}")


_PEOPLE_SPLIT = re.compile(r"\s*(?:/|→|->|>|,|·|\n)\s*")


def split_people(value: Any) -> tuple[str | None, str | None]:
    """'홍길동/김철수', '홍길동 → 김철수' → ('홍길동', '김철수')."""
    text = clean_text(value)
    if not text:
        return None, None
    parts = [p for p in _PEOPLE_SPLIT.split(text) if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def clean_text(value: Any) -> str | None:
    """앞뒤 공백 제거, 빈 문자열은 None. 줄바꿈은 원문 그대로 둔다."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def to_json(value: Any) -> Any:
    """staging raw 에 넣을 수 있는 형태로. 원본 손실 없이 문자열/숫자로만 바꾼다."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def auto_title(content: str | None, limit: int = 60) -> str | None:
    """원본 Excel 에는 제목 컬럼이 없다(§45). 내용 첫 줄 앞부분으로 만든다(B-09)."""
    if not content:
        return None
    first = content.strip().splitlines()[0].strip()
    return first if len(first) <= limit else first[: limit - 1] + "…"
