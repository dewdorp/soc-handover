"""방언에 맞는 전문검색 백엔드를 고른다. 상위 계층은 어느 쪽인지 알 필요가 없다."""
from __future__ import annotations

from functools import lru_cache

from app.core.db import dialect_name
from app.search.backends.base import SearchBackend


@lru_cache(maxsize=1)
def get_backend() -> SearchBackend:
    if dialect_name() == "postgresql":
        from app.search.backends.postgres import PostgresSearch
        return PostgresSearch()
    from app.search.backends.sqlite import SqliteSearch
    return SqliteSearch()


__all__ = ["SearchBackend", "get_backend"]
