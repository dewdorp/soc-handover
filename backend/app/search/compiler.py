"""검증된 DSL → SQLAlchemy 조건.

여기 오는 DSL 은 dsl.validate() 를 이미 통과했다. 필드명은 레지스트리의 FieldDef 로
치환되어 들어오므로, 사용자 문자열이 SQL 식별자가 되는 경로는 없다.

값은 파이썬 타입으로 변환한 뒤 **바인드 파라미터**로만 들어간다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ValidationFailed
from app.core.time import KST, quick_range
from app.models.handover import (ACK_NONE, Handover, HandoverAcknowledgement,
                                 HandoverStar, HandoverTag)
from app.models.reference import Tag
from app.search import fields as reg
from app.search.backends import get_backend
from app.search.backends.base import LIKE_ESCAPE, escape_like
from app.search.dsl import Filter, SearchRequest


@dataclass(frozen=True, slots=True)
class CompileContext:
    """DSL 만으로는 뜻이 정해지지 않는 값(내 확인상태, 즐겨찾기)을 위한 주체."""
    user_id: int


# --------------------------------------------------------------------------- 값 변환

def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationFailed(f"날짜 형식이 올바르지 않습니다: {value}") from exc


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=KST)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationFailed(f"시각 형식이 올바르지 않습니다: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _coerce(definition: reg.FieldDef, value):
    if value is None:
        return None
    if definition.kind == reg.KIND_DATE:
        return _as_date(value)
    if definition.kind == reg.KIND_DATETIME:
        return _as_datetime(value)
    if definition.kind == reg.KIND_INT:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(f"숫자가 필요합니다: {value}") from exc
    if definition.kind == reg.KIND_BOOL:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "y", "yes")
    return value


def _coerce_many(definition: reg.FieldDef, values) -> list:
    return [_coerce(definition, v) for v in values]


def _like(column, term: str, *, prefix: bool, suffix: bool):
    escaped = escape_like(term)
    pattern = f"{'%' if prefix else ''}{escaped}{'%' if suffix else ''}"
    return column.ilike(pattern, escape=LIKE_ESCAPE)


# --------------------------------------------------------------------------- 특수 필드

def _status_category_condition(flt: Filter) -> ColumnElement[bool]:
    values = flt.value if isinstance(flt.value, list) else [flt.value]
    sub = reg.status_codes_in_category(values[0]) if len(values) == 1 else None
    if sub is None:
        from app.models.reference import HandoverStatus
        sub = select(HandoverStatus.code).where(HandoverStatus.category.in_(values))
    condition = Handover.status_code.in_(sub)
    return not_(condition) if flt.op in (reg.OP_NOT_IN, reg.OP_NE) else condition


def _my_ack_condition(flt: Filter, ctx: CompileContext) -> ColumnElement[bool]:
    values = flt.value if isinstance(flt.value, list) else [flt.value]
    concrete = [v for v in values if v != ACK_NONE]
    has_none = ACK_NONE in values

    any_row = select(HandoverAcknowledgement.handover_id).where(
        HandoverAcknowledgement.user_id == ctx.user_id)

    parts: list[ColumnElement[bool]] = []
    if concrete:
        parts.append(Handover.id.in_(
            any_row.where(HandoverAcknowledgement.state.in_(concrete))))
    if has_none:
        # 확인 이력 자체가 없는 상태 = 내게는 NONE
        parts.append(Handover.id.not_in(any_row))

    if not parts:
        raise ValidationFailed("내 확인상태 필터에 값이 필요합니다.")
    condition = or_(*parts) if len(parts) > 1 else parts[0]
    return not_(condition) if flt.op in (reg.OP_NOT_IN, reg.OP_NE) else condition


def _starred_condition(flt: Filter, ctx: CompileContext) -> ColumnElement[bool]:
    mine = select(HandoverStar.handover_id).where(HandoverStar.user_id == ctx.user_id)
    wanted = _coerce(reg.HANDOVER_FIELDS["is_starred"], flt.value)
    return Handover.id.in_(mine) if wanted else Handover.id.not_in(mine)


def _tags_condition(flt: Filter) -> ColumnElement[bool]:
    tagged = select(HandoverTag.handover_id)
    if flt.op == reg.OP_IS_NULL:
        return Handover.id.not_in(tagged)
    if flt.op == reg.OP_IS_NOT_NULL:
        return Handover.id.in_(tagged)
    names = [str(v) for v in flt.value]
    return Handover.id.in_(
        tagged.join(Tag, Tag.id == HandoverTag.tag_id).where(Tag.name.in_(names)))


_SPECIAL = {"status_category", "my_ack_state", "is_starred", "tags"}


# --------------------------------------------------------------------------- 필터 컴파일

def compile_filter(flt: Filter, ctx: CompileContext) -> ColumnElement[bool]:
    definition = reg.HANDOVER_FIELDS[flt.field]

    if flt.field == "status_category":
        return _status_category_condition(flt)
    if flt.field == "my_ack_state":
        return _my_ack_condition(flt, ctx)
    if flt.field == "is_starred":
        return _starred_condition(flt, ctx)
    if flt.field == "tags":
        return _tags_condition(flt)

    column = definition.column
    if column is None:  # pragma: no cover - 레지스트리와 _SPECIAL 이 어긋난 경우
        raise ValidationFailed(f"처리할 수 없는 필드입니다: {flt.field}")

    op = flt.op
    if op == reg.OP_IS_NULL:
        return column.is_(None)
    if op == reg.OP_IS_NOT_NULL:
        return column.is_not(None)
    if op == reg.OP_EQ:
        return column == _coerce(definition, flt.value)
    if op == reg.OP_NE:
        return or_(column != _coerce(definition, flt.value), column.is_(None))
    if op == reg.OP_IN:
        return column.in_(_coerce_many(definition, flt.value))
    if op == reg.OP_NOT_IN:
        return or_(column.not_in(_coerce_many(definition, flt.value)), column.is_(None))
    if op == reg.OP_GTE:
        return column >= _coerce(definition, flt.value)
    if op == reg.OP_LTE:
        return column <= _coerce(definition, flt.value)
    if op == reg.OP_BETWEEN:
        start, end = _between_bounds(definition, flt.value)
        return column.between(start, end)
    if op == reg.OP_CONTAINS:
        return _like(column, str(flt.value), prefix=True, suffix=True)
    if op == reg.OP_NOT_CONTAINS:
        return or_(not_(_like(column, str(flt.value), prefix=True, suffix=True)),
                   column.is_(None))
    if op == reg.OP_STARTS_WITH:
        return _like(column, str(flt.value), prefix=False, suffix=True)
    if op == reg.OP_ENDS_WITH:
        return _like(column, str(flt.value), prefix=True, suffix=False)

    raise ValidationFailed(f"처리할 수 없는 연산자입니다: {op}")  # pragma: no cover


def _between_bounds(definition: reg.FieldDef, value):
    """["2026-08-01","2026-08-31"] 또는 'THIS_WEEK' 같은 토큰을 양끝 포함 범위로."""
    if isinstance(value, str):
        rng = quick_range(value)
        if definition.kind == reg.KIND_DATETIME:
            from app.core.time import end_of_day, start_of_day
            return start_of_day(rng.start), end_of_day(rng.end)
        return rng.start, rng.end
    start, end = value
    return _coerce(definition, start), _coerce(definition, end)


# --------------------------------------------------------------------------- 요청 전체

def compile_where(request: SearchRequest, ctx: CompileContext,
                  extra_filters: list[Filter] | None = None) -> list[ColumnElement[bool]]:
    """WHERE 조건 목록(서로 AND). 삭제 여부는 호출자가 명시적으로 넣는다."""
    conditions: list[ColumnElement[bool]] = []

    for flt in list(request.filters) + list(extra_filters or []):
        conditions.append(compile_filter(flt, ctx))

    if request.q and request.q.strip():
        conditions.append(get_backend().text_condition(request.q))

    return conditions


def compile_order(request: SearchRequest):
    """정렬. 상단고정은 항상 먼저, 마지막에 id 로 동점을 끊어 페이징을 안정화한다."""
    order = [Handover.is_pinned.desc()]
    for sort in request.sort:
        definition = reg.HANDOVER_FIELDS[sort.field]
        column = definition.column
        if column is None:
            continue
        order.append(column.desc() if sort.dir == "desc" else column.asc())
    if not request.sort:
        order.append(Handover.registered_date.desc())
    order.append(Handover.id.desc())
    return order


def build_statement(request: SearchRequest, ctx: CompileContext,
                    extra_filters: list[Filter] | None = None):
    stmt = select(Handover)
    conditions = compile_where(request, ctx, extra_filters)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt
