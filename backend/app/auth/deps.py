"""인증/인가 FastAPI 의존성."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.rbac import has_permission
from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import ACCESS_COOKIE, decode_access_token
from app.models.user import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise Unauthorized()

    payload = decode_access_token(token)
    if not payload:
        raise Unauthorized("세션이 만료되었습니다. 다시 로그인하십시오.")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise Unauthorized("사용할 수 없는 계정입니다.")

    request.state.user = user
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    try:
        return get_current_user(request, db)
    except Unauthorized:
        return None


def require(*permissions: str) -> Callable[..., User]:
    """라우터용 권한 게이트. 하나라도 없으면 403."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        missing = [p for p in permissions if not has_permission(user.role_code, p)]
        if missing:
            raise Forbidden(detail={"required": list(permissions), "missing": missing})
        return user

    return _dep


def require_password_changed(user: User = Depends(get_current_user)) -> User:
    """초기 비밀번호를 바꾸지 않은 계정은 일반 기능을 사용할 수 없다."""
    if user.must_change_password:
        raise Forbidden("초기 비밀번호를 변경해야 합니다.", detail={"must_change_password": True})
    return user
