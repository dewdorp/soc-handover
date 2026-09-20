"""인증 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.rbac import permissions_for
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.security import REFRESH_COOKIE, hash_token
from app.models.common import Notification
from app.services import ack_service
from app.models.user import RefreshToken, User
from app.schemas.auth import (ChangePasswordRequest, LoginRequest, MeResponse,
                              SessionInfo)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _me_payload(db: Session, user: User) -> MeResponse:
    # 배너 숫자는 '확인필요' 목록과 같은 기준이어야 한다(삭제된 건 제외).
    # 여기서 따로 세면 배너는 3건인데 목록은 2건인 일이 생긴다.
    pending = ack_service.pending_count(db, user.id)
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.is_read == false()
        )
    ) or 0
    return MeResponse(
        id=user.id, username=user.username, display_name=user.display_name,
        email=user.email, role_code=user.role_code, team=user.team,
        must_change_password=user.must_change_password, last_login_at=user.last_login_at,
        permissions=sorted(permissions_for(user.role_code)),
        pending_ack_count=pending, unread_notification_count=unread,
    )


@router.post("/login", response_model=MeResponse)
def login(payload: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    user = auth_service.login(db, response, username=payload.username,
                              password=payload.password, ctx=ctx)
    return _me_payload(db, user)


@router.post("/refresh", response_model=MeResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db),
            ctx: RequestContext = Depends(get_context)):
    user = auth_service.refresh_session(
        db, response, raw_refresh=request.cookies.get(REFRESH_COOKIE), ctx=ctx)
    return _me_payload(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db),
           ctx: RequestContext = Depends(get_context)):
    user = getattr(request.state, "user", None)
    if user is None:
        from app.auth.deps import get_optional_user
        user = get_optional_user(request, db)
    auth_service.logout(db, response, raw_refresh=request.cookies.get(REFRESH_COOKIE),
                        user=user, ctx=ctx)
    # 주의: 새 Response 를 만들어 돌려주면 위에서 쿠키를 지운 헤더가 버려져 브라우저에 세션이 남는다.
    # 주입받은 response 를 그대로 돌려줘야 Set-Cookie(삭제)가 함께 나간다.
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _me_payload(db, user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordRequest, response: Response,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user),
                    ctx: RequestContext = Depends(get_context)):
    auth_service.change_password(db, user=user, current=payload.current_password,
                                 new=payload.new_password, ctx=ctx)
    auth_service.clear_auth_cookies(response)
    # logout 과 같은 이유 — 주입받은 response 를 돌려줘야 쿠키 삭제가 실제로 나간다(비밀번호를 바꾸면 다시 로그인)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/sessions", response_model=list[SessionInfo])
def sessions(request: Request, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    current_hash = None
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        current_hash = hash_token(raw)
    rows = db.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .order_by(RefreshToken.issued_at.desc())
    ).all()
    return [
        SessionInfo(id=r.id, issued_at=r.issued_at, expires_at=r.expires_at,
                    client_ip=r.client_ip, user_agent=r.user_agent,
                    current=(r.token_hash == current_hash))
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    from app.core.time import now as _now
    token = db.get(RefreshToken, session_id)
    if token and token.user_id == user.id and token.revoked_at is None:
        token.revoked_at = _now()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
