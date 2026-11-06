"""운영 지식 API 스키마."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["운영 절차", "탐지·분석", "비상 대응", "장비·솔루션", "점검 체크리스트", "참고 자료"]
Visibility = Literal["ALL", "GROUPS"]


class ArticleCreate(BaseModel):
    category: Category = "운영 절차"
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=100000)
    visibility: Visibility = "ALL"
    group_ids: list[int] = Field(default_factory=list, max_length=30)
    is_pinned: bool = False
    review_due: date | None = None


class ArticleUpdate(BaseModel):
    category: Category | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=100000)
    visibility: Visibility | None = None
    group_ids: list[int] | None = Field(default=None, max_length=30)
    is_pinned: bool | None = None
    review_due: date | None = None
    version_no: int = Field(ge=1)


class ArticleOut(BaseModel):
    id: int
    category: str
    title: str
    body: str
    visibility: str
    group_ids: list[int]
    is_pinned: bool
    review_due: date | None
    version_no: int
    created_by: int
    updated_by: int | None
    created_at: datetime
    updated_at: datetime
    can_edit: bool
