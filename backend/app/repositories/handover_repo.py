"""인수인계 질의 전담. 서비스가 아니라 여기서만 SQL 을 만든다.

건수는 목록과 **분리한 count 쿼리**로 구한다(ARCHITECTURE.md §5.5). 목록 쿼리에
window function 을 붙이면 50만건에서 첫 페이지까지 느려진다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models.handover import (ACK_NONE, Handover, HandoverAcknowledgement,
                                 HandoverTag)
from app.models.reference import Company, HandoverStatus, Priority, Tag
from app.models.user import User
from app.search import fields as reg
from app.search.compiler import CompileContext, build_statement, compile_order
from app.search.dsl import Filter, SearchRequest

#: Facet 라벨을 어디서 가져오는가
_LABEL_SOURCES = {
    "company": (Company, Company.id, Company.name),
    "status": (HandoverStatus, HandoverStatus.code, HandoverStatus.name),
    "priority": (Priority, Priority.code, Priority.name),
    "user": (User, User.id, User.display_name),
}


def _deleted_scope(stmt: Select, *, include_deleted: bool) -> Select:
    return stmt if include_deleted else stmt.where(Handover.is_deleted.is_(False))


def count(db: Session, request: SearchRequest, ctx: CompileContext, *,
          include_deleted: bool, extra: list[Filter] | None = None) -> int:
    stmt = _deleted_scope(build_statement(request, ctx, extra), include_deleted=include_deleted)
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def count_all(db: Session) -> int:
    """필터를 걸지 않았을 때의 전체 건수. '전체 N건 / 검색결과 M건' 표시용(FR-A-09)."""
    return db.scalar(
        select(func.count()).select_from(Handover).where(Handover.is_deleted.is_(False))
    ) or 0


def search(db: Session, request: SearchRequest, ctx: CompileContext, *,
           include_deleted: bool, extra: list[Filter] | None = None) -> list[Handover]:
    stmt = _deleted_scope(build_statement(request, ctx, extra), include_deleted=include_deleted)
    offset = (request.page - 1) * request.size
    stmt = stmt.order_by(*compile_order(request)).offset(offset).limit(request.size)
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- Facet

def _facet_base(request: SearchRequest, ctx: CompileContext, target_field: str,
                *, include_deleted: bool, extra: list[Filter] | None):
    """Excel 자동필터와 같은 체감을 위해 **그 필드 자신의 필터는 빼고** 건수를 센다."""
    trimmed = request.model_copy(update={
        "filters": [f for f in request.filters if f.field != target_field],
        "sort": [],
    })
    return _deleted_scope(build_statement(trimmed, ctx, extra), include_deleted=include_deleted)


def facet(db: Session, request: SearchRequest, ctx: CompileContext, *, field: str,
          q: str = "", limit: int = 50, include_deleted: bool = False,
          extra: list[Filter] | None = None) -> list[dict[str, Any]]:
    definition = reg.HANDOVER_FIELDS[field]
    base = _facet_base(request, ctx, field, include_deleted=include_deleted, extra=extra)
    ids = base.with_only_columns(Handover.id).subquery()

    if field == "tags":
        rows = db.execute(
            select(Tag.name, func.count())
            .select_from(HandoverTag)
            .join(Tag, Tag.id == HandoverTag.tag_id)
            .where(HandoverTag.handover_id.in_(select(ids.c.id)))
            .group_by(Tag.name)
            .order_by(func.count().desc(), Tag.name)
        ).all()
        pairs = [(name, name, cnt) for name, cnt in rows]
        return _apply_text_filter(pairs, q, limit)

    if field == "my_ack_state":
        state = func.coalesce(HandoverAcknowledgement.state, ACK_NONE)
        rows = db.execute(
            select(state, func.count())
            .select_from(Handover)
            .outerjoin(HandoverAcknowledgement,
                       and_(HandoverAcknowledgement.handover_id == Handover.id,
                            HandoverAcknowledgement.user_id == ctx.user_id))
            .where(Handover.id.in_(select(ids.c.id)))
            .group_by(state)
            .order_by(func.count().desc())
        ).all()
        return _apply_text_filter([(v, v, c) for v, c in rows], q, limit)

    column = definition.column
    rows = db.execute(
        select(column, func.count())
        .select_from(Handover)
        .where(Handover.id.in_(select(ids.c.id)))
        .group_by(column)
        .order_by(func.count().desc())
    ).all()

    labels = _labels(db, definition, [v for v, _ in rows])
    pairs = [(v, labels.get(v, "(없음)" if v is None else str(v)), c) for v, c in rows]
    return _apply_text_filter(pairs, q, limit)


def _labels(db: Session, definition: reg.FieldDef, values: list) -> dict[Any, str]:
    source = _LABEL_SOURCES.get(definition.facet_source or "")
    real = [v for v in values if v is not None]
    if source is None or not real:
        return {}
    model, key, label = source
    rows = db.execute(select(key, label).where(key.in_(real))).all()
    return {k: v for k, v in rows}


def _apply_text_filter(pairs: list[tuple[Any, str, int]], q: str,
                       limit: int) -> list[dict[str, Any]]:
    """값이 많은 필드(담당자·태그)는 서버에서 걸러 상위 N 만 준다(FR-G-04)."""
    if q:
        needle = q.lower()
        pairs = [p for p in pairs if needle in str(p[1]).lower()]
    return [{"value": value, "label": label, "count": cnt}
            for value, label, cnt in pairs[:limit]]
