"""열람 그룹 라우터.

관리(만들기·이름 바꾸기·사용 중지·구성원·자료 이관)는 group:manage 권한이 필요하다.
'내 그룹'(GET /groups/mine)만 모든 로그인 사용자가 볼 수 있다 — 글 쓸 때 공개 범위를
고르는 데 필요하기 때문이다. 그룹 **목록**에는 다른 그룹의 업무 내용이 들어가지 않는다
(이름·건수만). 원문은 어디서도 그룹 관리 권한으로 열리지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.group import (GroupCreate, GroupMemberOut, GroupOut, GroupUpdate,
                               MembershipUpdate, MoveResult, MoveUnclassified, MyGroupOut,
                               UnclassifiedSummary)
from app.services import group_service

router = APIRouter(tags=["groups"], dependencies=[Depends(require_password_changed)])


@router.get("/groups/mine", response_model=list[MyGroupOut])
def my_groups(db: Session = Depends(get_db),
              actor: User = Depends(require("handover:read"))):
    """내가 속한 그룹. 업무를 쓸 때 공개 범위 선택지가 된다."""
    return group_service.my_groups(db, actor.id)


@router.get("/groups", response_model=list[GroupOut])
def list_groups(include_inactive: bool = True, db: Session = Depends(get_db),
                _: User = Depends(require("group:manage"))):
    return group_service.list_groups(db, include_inactive=include_inactive)


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: Session = Depends(get_db),
                 actor: User = Depends(require("group:manage")),
                 ctx: RequestContext = Depends(get_context)):
    group = group_service.create_group(db, name=payload.name, description=payload.description,
                                       sort_order=payload.sort_order, actor=actor, ctx=ctx)
    return _one(db, group.id)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(group_id: int, payload: GroupUpdate, db: Session = Depends(get_db),
                 actor: User = Depends(require("group:manage")),
                 ctx: RequestContext = Depends(get_context)):
    group_service.update_group(db, group_id, payload.model_dump(exclude_unset=True),
                               actor=actor, ctx=ctx)
    return _one(db, group_id)


@router.get("/groups/{group_id}/members", response_model=list[GroupMemberOut])
def members(group_id: int, db: Session = Depends(get_db),
            _: User = Depends(require("group:manage"))):
    return group_service.members(db, group_id)


@router.get("/users/{user_id}/groups", response_model=list[MyGroupOut])
def user_groups(user_id: int, db: Session = Depends(get_db),
                _: User = Depends(require("group:manage"))):
    """한 사람의 소속. 구성원 화면이 '넣기/빼기' 전후를 계산하는 데 쓴다."""
    return group_service.my_groups(db, user_id)


@router.put("/users/{user_id}/groups", response_model=list[MyGroupOut])
def set_memberships(user_id: int, payload: MembershipUpdate, db: Session = Depends(get_db),
                    actor: User = Depends(require("group:manage")),
                    ctx: RequestContext = Depends(get_context)):
    """한 사람의 소속을 통째로 바꾼다. 다음 요청부터 곧바로 적용된다(캐시 없음)."""
    return group_service.set_memberships(db, user_id, payload.group_ids,
                                         payload.default_group_id, actor=actor, ctx=ctx)


@router.get("/groups/unclassified/summary", response_model=UnclassifiedSummary)
def unclassified(db: Session = Depends(get_db),
                 _: User = Depends(require("group:manage"))):
    """아직 '미분류'에 남은 자료 — 관계사별 건수. 제목·내용은 주지 않는다."""
    return group_service.unclassified_summary(db)


@router.post("/groups/unclassified/move", response_model=MoveResult)
def move_unclassified(payload: MoveUnclassified, db: Session = Depends(get_db),
                      actor: User = Depends(require("group:manage")),
                      ctx: RequestContext = Depends(get_context)):
    return group_service.move_unclassified(db, to_group_id=payload.to_group_id,
                                           company_id=payload.company_id,
                                           limit=payload.limit, actor=actor, ctx=ctx)


def _one(db: Session, group_id: int) -> dict:
    rows = group_service.list_groups(db)
    return next(r for r in rows if r["id"] == group_id)
