"""저장된 보기 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.search import SavedViewCreate, SavedViewOut, SavedViewUpdate
from app.services import saved_view_service

router = APIRouter(tags=["saved-views"], dependencies=[Depends(require_password_changed)])


@router.get("/saved-views", response_model=list[SavedViewOut])
def list_views(target: str = Query(default="HANDOVER", max_length=20),
               db: Session = Depends(get_db),
               actor: User = Depends(require("savedview:personal"))):
    return saved_view_service.visible(db, actor, target)


@router.get("/saved-views/default", response_model=SavedViewOut | None)
def default_view(target: str = Query(default="HANDOVER", max_length=20),
                 db: Session = Depends(get_db),
                 actor: User = Depends(require("savedview:personal"))):
    """화면 첫 진입 시 적용할 보기(FR-A-11 / 개선제안 P-06)."""
    return saved_view_service.resolve_default(db, actor, target)


@router.post("/saved-views", response_model=SavedViewOut,
             status_code=status.HTTP_201_CREATED)
def create_view(payload: SavedViewCreate, db: Session = Depends(get_db),
                actor: User = Depends(require("savedview:personal")),
                ctx: RequestContext = Depends(get_context)):
    view = saved_view_service.create(db, payload.model_dump(), actor)
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="SAVED_VIEW", resource_id=view.id,
           after={"name": view.name, "scope": view.scope, "target": view.target})
    return view


@router.patch("/saved-views/{view_id}", response_model=SavedViewOut)
def update_view(view_id: int, payload: SavedViewUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require("savedview:personal")),
                ctx: RequestContext = Depends(get_context)):
    changes = payload.model_dump(exclude_unset=True)
    view = saved_view_service.update(db, view_id, changes, actor)
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="SAVED_VIEW", resource_id=view.id,
           after={k: v for k, v in changes.items() if k != "state"})
    return view


@router.delete("/saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(view_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("savedview:personal")),
                ctx: RequestContext = Depends(get_context)):
    saved_view_service.delete(db, view_id, actor)
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="SAVED_VIEW", resource_id=view_id, after={"deleted": True})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/saved-views/{view_id}/default", response_model=SavedViewOut)
def make_default(view_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require("savedview:personal"))):
    return saved_view_service.set_default(db, view_id, actor)
