"""사용자 관리 라우터. 역할 변경은 별도 감사 이벤트로 남긴다."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import get_current_user, require, require_password_changed
from app.auth.rbac import ALL_ROLES
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import Page, PageParams
from app.core.security import hash_password, validate_password_policy
from app.core.time import now
from app.models.user import RefreshToken, Role, User
from app.schemas.auth import UserBrief
from app.schemas.user import PasswordResetOut, UserCreate, UserOut, UserUpdate

router = APIRouter(tags=["users"], dependencies=[Depends(require_password_changed)])


@router.get("/users/lookup", response_model=list[UserBrief])
def lookup(q: str = Query(default="", max_length=50), limit: int = Query(default=20, le=100),
           db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """담당자 선택용 경량 목록(모든 로그인 사용자 사용 가능)."""
    stmt = select(User).where(User.is_active == true())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.username.ilike(like)))
    stmt = stmt.order_by(User.display_name).limit(limit)
    return list(db.scalars(stmt))


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(Role).order_by(Role.sort_order)).all()
    return [{"code": r.code, "name": r.name, "description": r.description} for r in rows]


@router.get("/users", response_model=Page[UserOut])
def list_users(q: str = Query(default="", max_length=50), role: str | None = None,
               active: bool | None = None, page: int = 1, size: int = 50,
               db: Session = Depends(get_db), _: User = Depends(require("user:read"))):
    params = PageParams(page=page, size=size)
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.username.ilike(like),
                              User.email.ilike(like)))
    if role:
        stmt = stmt.where(User.role_code == role.upper())
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(User.is_active.desc(), User.display_name)
        .offset(params.offset).limit(params.size)
    ).all()
    return Page.of([UserOut.model_validate(r) for r in rows], params, total)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db),
             _: User = Depends(require("user:manage"))):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")
    return UserOut.model_validate(user)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db),
                actor: User = Depends(require("user:manage")),
                ctx: RequestContext = Depends(get_context)):
    if payload.role_code.upper() not in ALL_ROLES:
        raise ValidationFailed(f"알 수 없는 역할입니다: {payload.role_code}")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise Conflict("이미 사용 중인 계정명입니다.")
    problems = validate_password_policy(payload.password, payload.username)
    if problems:
        raise ValidationFailed("비밀번호 정책을 만족하지 않습니다.", detail={"problems": problems})

    user = User(
        username=payload.username, display_name=payload.display_name,
        email=payload.email, team=payload.team, phone=payload.phone,
        role_code=payload.role_code.upper(), password_hash=hash_password(payload.password),
        must_change_password=payload.must_change_password, is_active=True,
    )
    db.add(user)
    db.flush()
    record(db, action=actions.USER_CREATE, ctx=ctx, user=actor, resource_type="USER",
           resource_id=user.id,
           after={"username": user.username, "role_code": user.role_code,
                  "display_name": user.display_name})
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require("user:manage")),
                ctx: RequestContext = Depends(get_context)):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")

    data = payload.model_dump(exclude_unset=True)
    if "role_code" in data and data["role_code"]:
        data["role_code"] = data["role_code"].upper()
        if data["role_code"] not in ALL_ROLES:
            raise ValidationFailed(f"알 수 없는 역할입니다: {data['role_code']}")
        if user.id == actor.id and data["role_code"] != actor.role_code:
            raise ValidationFailed("본인의 역할은 변경할 수 없습니다.")
    if "is_active" in data and data["is_active"] is False and user.id == actor.id:
        raise ValidationFailed("본인 계정은 비활성화할 수 없습니다.")

    before = {k: getattr(user, k) for k in data}
    role_changed = "role_code" in data and data["role_code"] != user.role_code
    for k, v in data.items():
        setattr(user, k, v)
    db.flush()

    # 역할이 바뀌거나 계정을 끈 순간, 그 사람이 열어 둔 비밀번호 금고도 닫는다.
    # 열람 권한을 뺐는데 화면에 평문이 남아 있으면 뺀 것이 아니다.
    if role_changed or data.get("is_active") is False:
        from app.services import vault_session_service
        vault_session_service.revoke_user(user.id)

    record(db, action=actions.USER_UPDATE, ctx=ctx, user=actor, resource_type="USER",
           resource_id=user.id, before=before, after=data)
    if role_changed:
        record(db, action=actions.ROLE_CHANGE, ctx=ctx, user=actor, resource_type="USER",
               resource_id=user.id,
               before={"role_code": before.get("role_code")},
               after={"role_code": user.role_code})
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetOut)
def reset_password(user_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("user:manage")),
                   ctx: RequestContext = Depends(get_context)):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")

    from app.services import vault_session_service
    vault_session_service.revoke_user(user.id)
    temp = secrets.token_urlsafe(12) + "!A1"
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    for t in db.scalars(select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        t.revoked_at = now()

    # 임시 비밀번호 값 자체는 감사 로그에 남기지 않는다(SECURITY §5)
    record(db, action=actions.PASSWORD_RESET, ctx=ctx, user=actor, resource_type="USER",
           resource_id=user.id, detail={"target_username": user.username})
    return PasswordResetOut(username=user.username, temporary_password=temp)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(require("user:manage")),
                    ctx: RequestContext = Depends(get_context)):
    """물리 삭제하지 않는다. 증적 보존을 위해 비활성화만 수행한다(ERD §8-5)."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")
    if user.id == actor.id:
        raise ValidationFailed("본인 계정은 비활성화할 수 없습니다.")
    user.is_active = False
    for t in db.scalars(select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        t.revoked_at = now()
    record(db, action=actions.USER_UPDATE, ctx=ctx, user=actor, resource_type="USER",
           resource_id=user.id, before={"is_active": True}, after={"is_active": False})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
