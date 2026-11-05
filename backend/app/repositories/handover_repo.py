"""인수인계 질의 전담. 서비스가 아니라 여기서만 SQL 을 만든다.

건수는 목록과 **분리한 count 쿼리**로 구한다(ARCHITECTURE.md §5.5). 목록 쿼리에
window function 을 붙이면 50만건에서 첫 페이지까지 느려진다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, false, func, select
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


def _scope(db: Session, stmt: Select, ctx: CompileContext, *,
           include_deleted: bool) -> Select:
    """목록·건수·패싯·Export 가 **빠짐없이** 지나는 범위 제한.

    여기에 두 가지를 겹친다.
      · 삭제 범위 — include_deleted 가 아니면 지운 건은 안 보인다.
      · 열람 그룹 — 내가 속한 그룹 · 전체 공개 · 내가 당사자인 건만(group_service 가 판정).

    왜 compile 단계가 아니라 여기인가: DSL 컴파일러는 세션을 모른다. 반대로 여기는
    모든 질의가 지나는 마지막 지점이라, 새 화면을 붙이면서 조건을 빼먹을 수가 없다.
    """
    from app.services import group_service

    if not include_deleted:
        stmt = stmt.where(Handover.is_deleted == false())
    return stmt.where(group_service.visible_clause(db, ctx.user_id))


def count(db: Session, request: SearchRequest, ctx: CompileContext, *,
          include_deleted: bool, extra: list[Filter] | None = None,
          cap: int | None = None) -> int:
    """건수. cap 을 주면 그 값까지만 세고 멈춘다(cap+1 을 돌려주면 '그 이상'이라는 뜻).

    50만 건에서 '지연 17만 건'을 정확히 세는 데 0.6초가 든다. Cockpit 타일처럼 '많다'만 알면 되는
    자리에서는 상한을 두고 센다 — 실측: 620ms → 20ms.
    """
    stmt = _scope(db, build_statement(request, ctx, extra), ctx,
                  include_deleted=include_deleted)
    if cap is not None:
        stmt = stmt.limit(cap + 1)
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def count_all(db: Session, ctx: CompileContext) -> int:
    """필터를 걸지 않았을 때 **내가 볼 수 있는** 전체 건수('전체 N건 / 검색결과 M건', FR-A-09).

    여기서 그룹 조건을 빼면 '전체 1,200건 · 검색결과 80건'처럼 보이면서, 볼 수 없는 건의
    개수가 숫자로 새어 나간다.
    """
    from app.services import group_service

    return db.scalar(
        select(func.count()).select_from(Handover)
        .where(Handover.is_deleted == false(), group_service.visible_clause(db, ctx.user_id))
    ) or 0


def search(db: Session, request: SearchRequest, ctx: CompileContext, *,
           include_deleted: bool, extra: list[Filter] | None = None) -> list[Handover]:
    stmt = _scope(db, build_statement(request, ctx, extra), ctx,
                  include_deleted=include_deleted)
    offset = (request.page - 1) * request.size
    stmt = stmt.order_by(*compile_order(request)).offset(offset).limit(request.size)
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- Facet

def _facet_base(db: Session, request: SearchRequest, ctx: CompileContext, target_field: str,
                *, include_deleted: bool, extra: list[Filter] | None):
    """Excel 자동필터와 같은 체감을 위해 **그 필드 자신의 필터는 빼고** 건수를 센다."""
    trimmed = request.model_copy(update={
        "filters": [f for f in request.filters if f.field != target_field],
        "sort": [],
    })
    return _scope(db, build_statement(trimmed, ctx, extra), ctx,
                  include_deleted=include_deleted)


def facet(db: Session, request: SearchRequest, ctx: CompileContext, *, field: str,
          q: str = "", limit: int = 50, include_deleted: bool = False,
          extra: list[Filter] | None = None) -> list[dict[str, Any]]:
    definition = reg.HANDOVER_FIELDS[field]
    base = _facet_base(db, request, ctx, field, include_deleted=include_deleted, extra=extra)
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


def iterate(db: Session, request: SearchRequest, ctx: CompileContext, *,
            include_deleted: bool, extra: list[Filter] | None = None, chunk: int = 1000):
    """Export 용. 화면과 **같은 조건·같은 정렬**로 전 행을 흘려보낸다(페이지 제한 없음).

    yield_per 로 chunk 단위로 가져오므로 10만 행이어도 메모리가 일정하다.
    """
    stmt = _scope(db, build_statement(request, ctx, extra), ctx,
                  include_deleted=include_deleted)
    stmt = stmt.order_by(*compile_order(request)).execution_options(yield_per=chunk)
    yield from db.scalars(stmt)
