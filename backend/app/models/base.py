"""ORM 베이스 및 이식성 타입.

PostgreSQL(운영)과 SQLite(개발/테스트)를 모두 지원해야 하므로,
방언 전용 타입은 variant 로 감싸서 한 곳에서만 분기한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, String, TypeDecorator, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# JSONB(PG) / JSON(SQLite)
JSONType = JSON().with_variant(JSONB, "postgresql")

# 문자열 리스트(changed_fields 등)는 이식성을 위해 JSON 배열로 저장한다.
StrListType = JSON().with_variant(JSONB, "postgresql")

# IP는 INET 대신 문자열로 저장한다(SQLite 호환 + IPv6 여유).
IPType = String(45)

class UTCDateTime(TypeDecorator):
    """항상 timezone-aware(UTC) 로 오가는 타임스탬프.

    SQLite 는 타임존을 보존하지 않아 naive 값이 돌아오고, 그대로 두면
    aware 값과 비교할 때 TypeError 가 난다(토큰 만료 비교 등). 여기서 한 번에 정규화한다.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


TZDateTime = UTCDateTime()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now(), index=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
