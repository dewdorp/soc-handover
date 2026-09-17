"""SQLite(개발·평가) 전문검색. 단순 LIKE 스캔이다.

운영은 PostgreSQL 이다. 여기서 성능을 재면 안 된다.
"""
from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from app.models.handover import Handover
from app.search.backends.base import LIKE_ESCAPE, escape_like


class SqliteSearch:
    name = "sqlite-like"

    def text_condition(self, q: str) -> ColumnElement[bool]:
        term = f"%{escape_like(q.strip())}%"
        return Handover.search_text.ilike(term, escape=LIKE_ESCAPE)

    def rank_expression(self, q: str) -> ColumnElement | None:
        return None  # 랭킹 없음 — 정렬은 호출자의 기본 정렬을 따른다
