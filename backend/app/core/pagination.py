"""페이지네이션 공통. 브라우저로 전체 데이터를 내려보내지 않기 위한 상한을 강제한다(§51)."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1, le=100_000)
    size: int = Field(default=settings.DEFAULT_PAGE_SIZE, ge=1)
    cursor: str | None = None

    @field_validator("size")
    @classmethod
    def _cap(cls, v: int) -> int:
        return min(v, settings.MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int
    total_all: int | None = None
    has_next: bool = False
    cursor: str | None = None

    @classmethod
    def of(cls, items: list[T], params: PageParams, total: int,
           total_all: int | None = None, cursor: str | None = None) -> "Page[T]":
        return cls(
            items=items,
            page=params.page,
            size=params.size,
            total=total,
            total_all=total_all,
            has_next=params.offset + len(items) < total,
            cursor=cursor,
        )
