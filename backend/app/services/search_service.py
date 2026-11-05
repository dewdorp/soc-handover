"""검색 실행 서비스.

GET 목록 · POST 검색 · Export · (나중에) AI 검색이 **모두 이 함수 하나**를 지난다.
그래서 "화면에 보이는 결과"와 "내려받은 결과"가 어긋날 수 없다(FR-F-07).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth.rbac import permissions_for
from app.core.errors import Forbidden, ValidationFailed
from app.core.pagination import Page, PageParams
from app.models.user import User
from app.repositories import handover_repo
from app.search import dsl, quick
from app.search.compiler import CompileContext
from app.search.dsl import SearchRequest


def _prepare(request: SearchRequest, actor: User) -> tuple[CompileContext, list]:
    perms = permissions_for(actor.role_code)
    dsl.validate(request, permissions=perms)

    if request.include_deleted and "handover:read_deleted" not in perms:
        raise Forbidden("삭제된 항목을 조회할 권한이 없습니다.")

    ctx = CompileContext(user_id=actor.id)
    extra = quick.expand(request.quick, actor.id)
    return ctx, extra


def run(db: Session, request: SearchRequest, actor: User):
    """목록 한 페이지 + 건수. 건수는 목록과 분리한 쿼리로 센다."""
    from app.api.v1 import handover_serde

    ctx, extra = _prepare(request, actor)
    total = handover_repo.count(db, request, ctx,
                                include_deleted=request.include_deleted, extra=extra)
    rows = handover_repo.search(db, request, ctx,
                                include_deleted=request.include_deleted, extra=extra)
    items = handover_serde.list_items(db, rows, actor.id)
    params = PageParams(page=request.page, size=request.size)
    # 조건이 없으면 '검색결과 수'가 곧 '전체 수'다 — 50만 건에서 같은 집계를 두 번 하면 1초가 든다.
    narrowed = bool(request.q or request.filters or request.quick or extra or request.include_deleted)
    total_all = handover_repo.count_all(db, ctx) if narrowed else total
    return Page.of(items, params, total, total_all=total_all)


def facet(db: Session, request: SearchRequest, actor: User, *, field: str,
          q: str = "", limit: int = 50) -> list[dict[str, Any]]:
    from app.search import fields as reg

    definition = reg.get_field(field)
    if definition is None or not definition.facetable:
        raise ValidationFailed(f"값 목록을 제공하지 않는 필드입니다: {field}",
                               detail={"allowed": reg.facetable_fields()})
    ctx, extra = _prepare(request, actor)
    return handover_repo.facet(db, request, ctx, field=field, q=q, limit=limit,
                               include_deleted=request.include_deleted, extra=extra)


def count_only(db: Session, request: SearchRequest, actor: User, *, cap: int | None = None) -> int:
    """Export 상한 확인 · Cockpit 타일 등, 목록을 만들지 않고 건수만 필요할 때.

    cap 을 주면 그 값까지만 센다 — 돌려준 값이 cap 보다 크면 '그 이상'이라는 뜻이다.
    """
    ctx, extra = _prepare(request, actor)
    return handover_repo.count(db, request, ctx,
                               include_deleted=request.include_deleted, extra=extra, cap=cap)


def iterate(db: Session, request: SearchRequest, actor: User):
    """Export 가 쓰는 전 행 순회. 목록과 같은 검증·Quick 펼침·권한 규칙을 지난다."""
    ctx, extra = _prepare(request, actor)
    yield from handover_repo.iterate(db, request, ctx,
                                     include_deleted=request.include_deleted, extra=extra)
