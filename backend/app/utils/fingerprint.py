"""중복 판정용 지문(ASSUMPTIONS D-02).

    sha256( norm(관계사) | 날짜(YYYY-MM-DD) | norm(내용 앞 500자) | norm(전달자) )

norm = 유니코드 정규화(NFKC) + 공백·특수문자 제거 + 소문자화.
"A사 ", "a사", "A 사" 가 같은 값이 되도록, 표기 흔들림을 흡수하는 것이 목적이다.

지문이 같다고 지우지 않는다. **의심 표시만** 하고 사람이 고른다(§48).
UI 로 등록한 건과 Excel 로 가져온 건이 같은 식을 써야 서로를 알아볼 수 있다.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_NOISE = re.compile(r"[\W_]+", re.UNICODE)


def norm(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _NOISE.sub("", text).lower()


def fingerprint(company: str | None, date_iso: str | None,
                content: str | None, sender: str | None) -> str:
    parts = [
        norm(company),
        (date_iso or "").strip(),
        norm((content or "")[:500]),
        norm(sender),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
