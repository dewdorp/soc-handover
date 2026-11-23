"""필드 / 장문 텍스트 Diff (FR-B-03).

· 필드 단위 diff 는 before→after 값 쌍을 그대로 돌려준다.
· 장문 텍스트는 word 단위 ops 로 쪼개 화면이 하이라이트할 수 있게 한다.

토큰은 "공백 덩어리 | 비공백 덩어리" 로 나눈다. 한국어는 형태소 경계를 알 수 없으므로
어절(띄어쓰기) 단위가 가장 안전하고, 토큰을 그대로 이어 붙이면 원문이 정확히 복원된다.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

_TOKEN = re.compile(r"\s+|\S+")

#: word-diff 를 적용할 장문 필드. 나머지는 값 교체로만 표시한다.
LONG_TEXT_FIELDS: frozenset[str] = frozenset({"title", "content", "remark"})

#: 이 길이를 넘으면 word-diff 비용(O(n²))이 응답을 망치므로 통째 교체로 낮춘다.
_MAX_WORD_DIFF_CHARS = 20_000


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def word_diff(before: str | None, after: str | None) -> list[dict[str, str]]:
    """[{"op": "equal"|"delete"|"insert", "text": "..."}] 형태의 ops 목록."""
    b_raw, a_raw = before or "", after or ""
    if b_raw == a_raw:
        return [{"op": "equal", "text": b_raw}] if b_raw else []

    if len(b_raw) + len(a_raw) > _MAX_WORD_DIFF_CHARS:
        ops: list[dict[str, str]] = []
        if b_raw:
            ops.append({"op": "delete", "text": b_raw})
        if a_raw:
            ops.append({"op": "insert", "text": a_raw})
        return ops

    b, a = tokenize(b_raw), tokenize(a_raw)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=b, b=a, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": "".join(b[i1:i2])})
        elif tag == "delete":
            ops.append({"op": "delete", "text": "".join(b[i1:i2])})
        elif tag == "insert":
            ops.append({"op": "insert", "text": "".join(a[j1:j2])})
        else:  # replace → delete + insert 로 펼친다
            ops.append({"op": "delete", "text": "".join(b[i1:i2])})
            ops.append({"op": "insert", "text": "".join(a[j1:j2])})
    return ops


def _doc_label(doc: Any) -> str | None:
    from app.core import richdoc
    if not doc:
        return None
    s = richdoc.summary(doc) or {}
    parts = [f"표 {s['tables']}" if s.get("tables") else "",
             f"그림 {s['images']}" if s.get("images") else "",
             f"로그·코드 {s['code_blocks']}" if s.get("code_blocks") else ""]
    return "서식 있음" + (f" ({' · '.join(p for p in parts if p)})" if any(parts) else "")


def field_diff(before: dict[str, Any], after: dict[str, Any],
               fields: list[str]) -> list[dict[str, Any]]:
    """필드별 before/after. 장문 필드에는 word-diff ops 를 덧붙인다."""
    out: list[dict[str, Any]] = []
    for name in fields:
        b, a = before.get(name), after.get(name)
        if name.endswith("_doc"):
            # 서식 구조는 통째로 보내지 않는다 — 글의 차이는 content 의 단어 비교가 보여 주고,
            # 여기서는 '무엇이 몇 개 있었는지'만 알린다(표 · 그림 · 로그 블록 수).
            b, a = _doc_label(b), _doc_label(a)
        entry: dict[str, Any] = {"field": name, "before": b, "after": a}
        if name in LONG_TEXT_FIELDS and (isinstance(b, str) or isinstance(a, str)):
            entry["ops"] = word_diff(b if isinstance(b, str) else "",
                                     a if isinstance(a, str) else "")
        out.append(entry)
    return out
