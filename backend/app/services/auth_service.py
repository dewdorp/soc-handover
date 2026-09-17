"""로그인/토큰/세션 서비스. 쿠키 설정과 감사 기록을 한 곳에 모은다."""
from __future__ import annotations

from datetime import timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.providers.local import LocalAuthProvider
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import Unauthorized, ValidationFailed
from app.core.security import (ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE,
                               create_access_token, hash_password, hash_token,
                               new_csrf_token, new_refresh_token,
                               validate_password_policy, verify_password)
from app.core.time import now
from app.models.user import LoginAttempt, RefreshToken, User

GENERIC_LOGIN_ERROR = "아이디 또는 비밀번호가 올바르지 않습니다."


# ---------------- 쿠키 ----------------

def _cookie_kwargs(max_age: int, http_only: bool = True) -> dict:
    return {
        "max_age": max_age,
        "httponly": http_only,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
        "path": "/",
        "domain": settings.COOKIE_DOMAIN,
    }


def set_auth_cookies(resp: Response, *, access: str, refresh: str, csrf: str) -> None:
    resp.set_cookie(ACCESS_COOKIE, access,
                    **_cookie_kwargs(settings.ACCESS_TOKEN_MINUTES * 60))
    resp.set_cookie(REFRESH_COOKIE, refresh,
                    **_cookie_kwargs(settings.REFRESH_TOKEN_HOURS * 3600))
    # CSRF 쿠키는 JS가 읽어 헤더에 실어야 하므로 HttpOnly 가 아니다(더블 서브밋).
    resp.set_cookie(CSRF_COOKIE, csrf,
                    **_cookie_kwargs(settings.REFRESH_TOKEN_HOURS * 3600, http_only=False))


def clear_auth_cookies(resp: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        resp.delete_cookie(name, path="/", domain=settings.COOKIE_DOMAIN)


# ---------------- 로그인 ----------------

def _log_attempt(db: Session, username: str, ctx: RequestContext,
                 success: bool, reason: str | None) -> None:
    db.add(LoginAttempt(username=username[:64], client_ip=ctx.client_ip,
                        success=success, reason=reason, attempted_at=now()))


def _issue_refresh(db: Session, user: User, ctx: RequestContext) -> str:
    raw, hashed = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=hashed, issued_at=now(),
        expires_at=now() + timedelta(hours=settings.REFRESH_TOKEN_HOURS),
        client_ip=ctx.client_ip, user_agent=ctx.user_agent,
    ))
    return raw


def login(db: Session, resp: Response, *, username: str, password: str,
          ctx: RequestContext) -> User:
    provider = LocalAuthProvider(db)
    result = provider.authenticate(username, password)

    if not result.ok:
        _log_attempt(db, username, ctx, False, result.reason)
        record(db, action=actions.LOGIN_FAILURE, ctx=ctx, username=username,
               result="FAILURE", error_message=result.reason,
               resource_type="USER", resource_id=username)
        # 예외를 던지면 요청 트랜잭션이 롤백되므로, 실패 카운트/증적은 먼저 확정한다.
        # (이 커밋이 없으면 계정 잠금 자체가 동작하지 않는다)
        db.commit()
        if result.reason == "LOCKED":
            raise Unauthorized("계정이 일시적으로 잠겼습니다. 잠시 후 다시 시도하십시오.")
        raise Unauthorized(GENERIC_LOGIN_ERROR)

    user = db.get(User, result.user_id)
    assert user is not None

    _log_attempt(db, username, ctx, True, None)
    access = create_access_token(user_id=user.id, username=user.username, role=user.role_code)
    refresh = _issue_refresh(db, user, ctx)
    set_auth_cookies(resp, access=access, refresh=refresh, csrf=new_csrf_token())
    record(db, action=actions.LOGIN_SUCCESS, ctx=ctx, user=user,
           resource_type="USER", resource_id=user.id)
    return user


def refresh_session(db: Session, resp: Response, *, raw_refresh: str | None,
                    ctx: RequestContext) -> User:
    if not raw_refresh:
        raise Unauthorized()
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh)))
    if token is None:
        raise Unauthorized("세션이 유효하지 않습니다.")

    if token.revoked_at is not None:
        # 이미 회전된 토큰의 재사용 → 탈취 의심. 해당 사용자 전체 세션 폐기(SECURITY §1.2)
        for t in db.scalars(select(RefreshToken).where(
                RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))):
            t.revoked_at = now()
        record(db, action=actions.LOGIN_FAILURE, ctx=ctx, username=None,
               resource_type="REFRESH_TOKEN", resource_id=token.id, result="FAILURE",
               error_message="REFRESH_REUSE_DETECTED")
        clear_auth_cookies(resp)
        db.commit()  # 폐기와 증적은 롤백되면 안 된다
        raise Unauthorized("세션이 유효하지 않습니다. 다시 로그인하십시오.")

    if token.expires_at <= now():
        raise Unauthorized("세션이 만료되었습니다. 다시 로그인하십시오.")

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("사용할 수 없는 계정입니다.")

    token.revoked_at = now()
    new_raw = _issue_refresh(db, user, ctx)
    access = create_access_token(user_id=user.id, username=user.username, role=user.role_code)
    set_auth_cookies(resp, access=access, refresh=new_raw, csrf=new_csrf_token())
    return user


def logout(db: Session, resp: Response, *, raw_refresh: str | None, user: User | None,
           ctx: RequestContext) -> None:
    if raw_refresh:
        token = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw_refresh)))
        if token and token.revoked_at is None:
            token.revoked_at = now()
    clear_auth_cookies(resp)
    if user:
        record(db, action=actions.LOGOUT, ctx=ctx, user=user,
               resource_type="USER", resource_id=user.id)


def change_password(db: Session, *, user: User, current: str, new: str,
                    ctx: RequestContext) -> None:
    if not verify_password(current, user.password_hash):
        record(db, action=actions.PASSWORD_CHANGE, ctx=ctx, user=user, result="FAILURE",
               error_message="CURRENT_MISMATCH", resource_type="USER", resource_id=user.id)
        db.commit()  # 실패 증적은 롤백되지 않도록 먼저 확정한다
        raise ValidationFailed("현재 비밀번호가 올바르지 않습니다.")
    problems = validate_password_policy(new, user.username)
    if problems:
        raise ValidationFailed("비밀번호 정책을 만족하지 않습니다.", detail={"problems": problems})
    if verify_password(new, user.password_hash):
        raise ValidationFailed("이전과 다른 비밀번호를 사용하십시오.")

    user.password_hash = hash_password(new)
    user.must_change_password = False
    # 비밀번호 변경 시 기존 세션을 모두 폐기한다.
    for t in db.scalars(select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        t.revoked_at = now()
    record(db, action=actions.PASSWORD_CHANGE, ctx=ctx, user=user,
           resource_type="USER", resource_id=user.id)
