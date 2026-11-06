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
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_pinned: bool = False
    review_due: date | None = None
    change_note: str | None = Field(default=None, max_length=300)


class ArticleUpdate(BaseModel):
    category: Category | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=100000)
    visibility: Visibility | None = None
    group_ids: list[int] | None = Field(default=None, max_length=30)
    tags: list[str] | None = Field(default=None, max_length=20)
    is_pinned: bool | None = None
    review_due: date | None = None
    change_note: str | None = Field(default=None, max_length=300)
    version_no: int = Field(ge=1)


class ArticleOut(BaseModel):
    id: int
    category: str
    title: str
    body: str
    visibility: str
    group_ids: list[int]
    group_names: list[str] = []
    tags: list[str] = []
    is_pinned: bool
    review_due: date | None
    review_overdue: bool = False
    version_no: int
    created_by: int
    created_by_name: str | None = None
    updated_by: int | None
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False
    can_edit: bool


class RevisionOut(BaseModel):
    version_no: int
    title: str
    category: str
    visibility: str
    tags: str = ""
    change_note: str | None = None
    changed_by: int | None = None
    changed_by_name: str | None = None
    changed_at: datetime
    body_chars: int = 0


class RevisionBody(BaseModel):
    version_no: int
    title: str
    category: str
    body: str
    tags: str = ""
    visibility: str
    change_note: str | None = None
    changed_at: datetime


class LinkCreate(BaseModel):
    handover_id: int


class LinkOut(BaseModel):
    handover_id: int
    title: str
    status_code: str | None = None
    created_at: datetime | None = None


class SuggestOut(BaseModel):
    id: int
    title: str
    category: str
    score: int = 0
