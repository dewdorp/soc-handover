"""필터 DSL 정의와 검증 (ARCHITECTURE.md §5.2).

목록·Export·AI 검색이 **같은 DSL** 을 쓴다. 그래서 "화면에 보이는 결과"와
"내려받은 결과"가 구조적으로 같을 수밖에 없다(FR-F-07).

검증은 여기서 끝낸다. compiler 는 이미 검증된 DSL 만 받는다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.errors import ValidationFailed
from app.core.time import QUICK_RANGE_TOKENS
from app.search import fields as reg

MAX_FILTERS = 30
MAX_SORTS = 4
MAX_VALUES = 500


class Filter(BaseModel):
    field: str = Field(min_length=1, max_length=40)
    op: str = Field(min_length=1, max_length=20)
    value: Any = None

    model_config = {"extra": "forbid"}


class Sort(BaseModel):
    field: str = Field(min_length=1, max_length=40)
    dir: Literal["asc", "desc"] = "asc"

    model_config = {"extra": "forbid"}


class SearchRequest(BaseModel):
    """목록/검색 요청. filters 끼리는 AND 다."""
    q: str | None = Field(default=None, max_length=200)
    filters: list[Filter] = Field(default_factory=list, max_length=MAX_FILTERS)
    sort: list[Sort] = Field(default_factory=list, max_length=MAX_SORTS)
    quick: list[str] = Field(default_factory=list, max_length=10)
    page: int = Field(default=1, ge=1, le=100_000)
    size: int = Field(default=settings.DEFAULT_PAGE_SIZE, ge=1)
    cursor: str | None = Field(default=None, max_length=200)
    include_deleted: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("size")
    @classmethod
    def _cap(cls, v: int) -> int:
        return min(v, settings.MAX_PAGE_SIZE)


def _reject(message: str, **detail) -> None:
    raise ValidationFailed(message, detail=detail)


def validate(request: SearchRequest, *, permissions: frozenset[str] | set[str]) -> None:
    """알 수 없는 필드/연산자/값 형태를 여기서 전부 걸러낸다."""
    for flt in request.filters:
        definition = reg.get_field(flt.field)
        if definition is None:
            _reject(f"검색할 수 없는 필드입니다: {flt.field}",
                    field=flt.field, allowed=sorted(reg.HANDOVER_FIELDS))
        if definition.requires_permission and definition.requires_permission not in permissions:
            _reject(f"해당 필드로 검색할 권한이 없습니다: {flt.field}", field=flt.field)
        if not definition.supports(flt.op):
            _reject(f"'{definition.label}' 에는 사용할 수 없는 연산자입니다: {flt.op}",
                    field=flt.field, op=flt.op, allowed=sorted(definition.ops))
        _validate_value(definition, flt)

    for sort in request.sort:
        definition = reg.get_field(sort.field)
        if definition is None or not definition.sortable:
            _reject(f"정렬할 수 없는 필드입니다: {sort.field}",
                    field=sort.field, allowed=reg.sortable_fields())

    from app.search.quick import QUICK_FILTERS
    for token in request.quick:
        if token.upper() not in QUICK_FILTERS:
            _reject(f"알 수 없는 Quick Filter 입니다: {token}",
                    allowed=sorted(QUICK_FILTERS))


def _validate_value(definition: reg.FieldDef, flt: Filter) -> None:
    op, value = flt.op, flt.value

    if op in (reg.OP_IS_NULL, reg.OP_IS_NOT_NULL):
        return  # 값이 필요 없다

    if value is None:
        _reject(f"'{definition.label}' 필터에 값이 필요합니다.", field=flt.field, op=op)

    if op in (reg.OP_IN, reg.OP_NOT_IN, reg.OP_ANY_OF_TAGS):
        if not isinstance(value, list) or not value:
            _reject(f"'{definition.label}' 의 {op} 에는 비어 있지 않은 목록이 필요합니다.",
                    field=flt.field, op=op)
        if len(value) > MAX_VALUES:
            _reject(f"한 번에 지정할 수 있는 값은 {MAX_VALUES}개까지입니다.",
                    field=flt.field, op=op, given=len(value))
        return

    if op == reg.OP_BETWEEN:
        # 날짜는 ["2026-08-01","2026-08-31"] 또는 "THIS_WEEK" 같은 토큰을 허용한다.
        if isinstance(value, str):
            if definition.kind not in (reg.KIND_DATE, reg.KIND_DATETIME):
                _reject(f"'{definition.label}' 의 between 에는 [시작, 끝] 이 필요합니다.",
                        field=flt.field)
            if value.upper() not in QUICK_RANGE_TOKENS:
                _reject(f"알 수 없는 기간 토큰입니다: {value}",
                        field=flt.field, allowed=list(QUICK_RANGE_TOKENS))
            return
        if not isinstance(value, list) or len(value) != 2:
            _reject(f"'{definition.label}' 의 between 에는 [시작, 끝] 두 값이 필요합니다.",
                    field=flt.field)
        return

    if isinstance(value, (list, dict)):
        _reject(f"'{definition.label}' 의 {op} 에는 단일 값이 필요합니다.",
                field=flt.field, op=op)

    if definition.kind == reg.KIND_TEXT and isinstance(value, str) and len(value) > 500:
        _reject("검색어가 너무 깁니다(500자).", field=flt.field)
