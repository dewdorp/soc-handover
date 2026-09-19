"""검색/Facet/저장된 보기 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.search.dsl import SearchRequest


class FacetRequest(SearchRequest):
    """현재 적용 중인 필터를 그대로 받아 '남는 값'의 건수를 센다(Excel 자동필터 체감)."""
    field: str = Field(min_length=1, max_length=40)
    facet_q: str = Field(default="", max_length=100)
    limit: int = Field(default=50, ge=1, le=500)


class FacetValue(BaseModel):
    value: Any
    label: str
    count: int


class FieldInfo(BaseModel):
    name: str
    label: str
    kind: str
    ops: list[str]
    sortable: bool
    facetable: bool
    facet_source: str | None = None


class QuickFilterInfo(BaseModel):
    token: str
    label: str


class SearchCapabilities(BaseModel):
    """프론트가 필터 UI 를 구성하는 근거. 화면이 목록을 하드코딩하지 않게 한다."""
    fields: list[FieldInfo]
    quick_filters: list[QuickFilterInfo]
    operators: list[str]
    backend: str
    max_filters: int
    max_page_size: int


class GlobalSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    scope: list[Literal["handover", "task", "schedule"]] = Field(
        default_factory=lambda: ["handover", "task", "schedule"])
    limit: int = Field(default=8, ge=1, le=50)


class GlobalHit(BaseModel):
    type: str
    id: int
    title: str
    snippet: str | None = None
    company: str | None = None
    date: Any = None
    matched: list[str] = []       # 걸린 칸: 제목 · 내용 · 비고 · 관계사 · 전달자 · 담당자 · 확인자 · 태그


class GlobalSearchResponse(BaseModel):
    q: str
    hits: list[GlobalHit]
    totals: dict[str, int]


# --------------------------------------------------------------------------- Saved View

class SavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target: str = Field(default="HANDOVER", max_length=20)
    scope: Literal["PERSONAL", "SHARED"] = "PERSONAL"
    description: str | None = Field(default=None, max_length=500)
    #: 필터뿐 아니라 그리드 상태(보이는 컬럼·너비·순서·밀도)까지 통째로 담는다(§15).
    state: dict[str, Any]
    sort_order: int = 100


class SavedViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    scope: Literal["PERSONAL", "SHARED"] | None = None
    state: dict[str, Any] | None = None
    sort_order: int | None = None


class SavedViewOut(BaseModel):
    id: int
    name: str
    description: str | None
    scope: str
    owner_id: int | None
    target: str
    state: dict[str, Any]
    is_default: bool
    sort_order: int
    created_by: int | None
    updated_at: datetime

    model_config = {"from_attributes": True}
