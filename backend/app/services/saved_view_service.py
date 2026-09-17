"""저장된 보기(Saved View) — 필터 + 그리드 상태 전체를 저장한다(§15, FR-A-11).

개인(PERSONAL)과 공용(SHARED)을 구분한다. 공용은 팀 전체가 보므로 만들고 고치는 데
`savedview:shared` 권한이 필요하고(MANAGER+), 개인 보기는 남이 볼 수 없다.

기본 보기(is_default)는 **사용자 × 대상마다 하나**다. 새로 지정하면 나머지는 해제된다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.rbac import has_permission
from app.core.errors import Conflict, Forbidden, NotFound
from app.models.common import SavedView
from app.models.user import User

SCOPE_PERSONAL = "PERSONAL"
SCOPE_SHARED = "SHARED"


def _require_shared_permission(actor: User) -> None:
    if not has_permission(actor.role_code, "savedview:shared"):
        raise Forbidden("공용 보기를 만들거나 수정할 권한이 없습니다.")


def visible(db: Session, actor: User, target: str = "HANDOVER") -> list[SavedView]:
    """내 개인 보기 + 모든 공용 보기."""
    stmt = (select(SavedView)
            .where(SavedView.target == target.upper())
            .where(or_(SavedView.scope == SCOPE_SHARED,
                       SavedView.owner_id == actor.id))
            .order_by(SavedView.scope, SavedView.sort_order, SavedView.name))
    return list(db.scalars(stmt))


def get_or_404(db: Session, view_id: int, actor: User) -> SavedView:
    view = db.get(SavedView, view_id)
    if view is None:
        raise NotFound("저장된 보기를 찾을 수 없습니다.")
    if view.scope == SCOPE_PERSONAL and view.owner_id != actor.id:
        # 남의 개인 보기는 존재 자체를 드러내지 않는다.
        raise NotFound("저장된 보기를 찾을 수 없습니다.")
    return view


def _assert_editable(view: SavedView, actor: User) -> None:
    if view.scope == SCOPE_SHARED:
        _require_shared_permission(actor)
    elif view.owner_id != actor.id:
        raise Forbidden("본인의 보기만 수정할 수 있습니다.")


def create(db: Session, payload: dict[str, Any], actor: User) -> SavedView:
    scope = payload.get("scope", SCOPE_PERSONAL)
    if scope == SCOPE_SHARED:
        _require_shared_permission(actor)

    target = str(payload.get("target", "HANDOVER")).upper()
    owner_id = None if scope == SCOPE_SHARED else actor.id

    duplicate = db.scalar(
        select(SavedView).where(SavedView.scope == scope, SavedView.target == target,
                                SavedView.name == payload["name"],
                                SavedView.owner_id.is_(None) if owner_id is None
                                else SavedView.owner_id == owner_id))
    if duplicate is not None:
        raise Conflict(f"같은 이름의 보기가 이미 있습니다: {payload['name']}")

    view = SavedView(
        name=payload["name"], description=payload.get("description"), scope=scope,
        owner_id=owner_id, target=target, state=payload["state"],
        sort_order=payload.get("sort_order", 100), created_by=actor.id)
    db.add(view)
    db.flush()
    return view


def update(db: Session, view_id: int, changes: dict[str, Any], actor: User) -> SavedView:
    view = get_or_404(db, view_id, actor)
    _assert_editable(view, actor)

    new_scope = changes.get("scope")
    if new_scope and new_scope != view.scope:
        _require_shared_permission(actor)
        view.owner_id = None if new_scope == SCOPE_SHARED else actor.id

    for key, value in changes.items():
        setattr(view, key, value)
    db.flush()
    return view


def delete(db: Session, view_id: int, actor: User) -> None:
    view = get_or_404(db, view_id, actor)
    _assert_editable(view, actor)
    db.delete(view)
    db.flush()


def set_default(db: Session, view_id: int, actor: User) -> SavedView:
    """기본 보기 지정.

    개인 보기를 기본으로 하면 나에게만 적용되고, 공용 보기를 기본으로 하면 팀 전체의
    기본이 되므로 공용 권한이 필요하다. 조회 시에는 내 개인 기본이 공용 기본을 이긴다
    (resolve_default). SavedView.is_default 하나로 두 층을 표현하는 구조라 범위를
    명시적으로 나눠 둔다.
    """
    view = get_or_404(db, view_id, actor)
    if view.scope == SCOPE_SHARED:
        _require_shared_permission(actor)
        scope_filter = SavedView.scope == SCOPE_SHARED
    else:
        scope_filter = (SavedView.scope == SCOPE_PERSONAL) & (SavedView.owner_id == actor.id)

    others = db.scalars(
        select(SavedView).where(SavedView.target == view.target,
                                SavedView.is_default.is_(True), scope_filter)).all()
    for other in others:
        other.is_default = False
    view.is_default = True
    db.flush()
    return view


def resolve_default(db: Session, actor: User, target: str = "HANDOVER") -> SavedView | None:
    """화면을 열 때 적용할 보기. 내 개인 기본이 팀 공용 기본보다 우선한다."""
    target = target.upper()
    mine = db.scalar(
        select(SavedView).where(SavedView.target == target,
                                SavedView.scope == SCOPE_PERSONAL,
                                SavedView.owner_id == actor.id,
                                SavedView.is_default.is_(True)))
    if mine is not None:
        return mine
    return db.scalar(
        select(SavedView).where(SavedView.target == target,
                                SavedView.scope == SCOPE_SHARED,
                                SavedView.is_default.is_(True)))
