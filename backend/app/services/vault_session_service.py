"""비밀번호 금고 단기 열람 세션. 인증 1회로 현재 화면의 허용된 항목을 보여준다.

인증은 서버에서 수행한다. 평문이나 세션 토큰을 DB·쿠키·브라우저 저장소에 남기지 않는다.
토큰은 요청 사용자 · 비밀번호 해시 · 브라우저 식별정보에 묶고 프로세스 메모리에만 보관한다.
앱 재시작 · 로그아웃 · 비밀번호 변경 시 만료된다.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.context import RequestContext
from app.core.errors import Forbidden, RateLimited
from app.core.security import verify_password
from app.models.user import User
from app.services import settings_service

_lock = threading.RLock()
_sessions: dict[str, "VaultSession"] = {}
_failures: dict[int, list[float]] = {}
_MAX_SESSIONS = 1000


@dataclass
class VaultSession:
    user_id: int
    hash_fingerprint: str
    client_ip: str
    user_agent: str
    expires_at: float
    max_expires_at: float


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fingerprint(actor: User) -> str:
    return hashlib.sha256((actor.password_hash or "").encode("utf-8")).hexdigest()


def _identity(ctx: RequestContext | None) -> tuple[str, str]:
    return (ctx.client_ip if ctx else "", ctx.user_agent if ctx else "")


#: 한 번 인증으로 이어서 볼 수 있는 **절대 상한**(분). 설정으로도 넘길 수 없다.
HARD_MAX_MINUTES = 15
#: 한 번에 열어 두는 기본 시간의 상한(분).
HARD_TTL_MINUTES = 10


def _minutes(db: Session) -> tuple[int, int]:
    """(한 번 열어 두는 시간, 연속 유지 상한) — 설정값이 이상해도 상한을 넘지 않는다."""
    try:
        ttl_raw = int(settings_service.get_value(db, "credential.unlock_minutes") or 5)
    except (TypeError, ValueError):
        ttl_raw = 5
    try:
        max_raw = int(settings_service.get_value(db, "credential.max_session_minutes") or HARD_MAX_MINUTES)
    except (TypeError, ValueError):
        max_raw = HARD_MAX_MINUTES
    ttl = max(1, min(HARD_TTL_MINUTES, ttl_raw))
    max_ttl = max(ttl, min(HARD_MAX_MINUTES, max_raw))
    return ttl, max_ttl


def _cleanup_locked(now: float) -> None:
    for key, state in list(_sessions.items()):
        if now >= state.expires_at or now >= state.max_expires_at:
            _sessions.pop(key, None)
    for user_id, timestamps in list(_failures.items()):
        keep = [x for x in timestamps if now - x < 300]
        if keep:
            _failures[user_id] = keep
        else:
            _failures.pop(user_id, None)


def unlock(db: Session, actor: User, password: str, ctx: RequestContext | None) -> dict:
    now = time.monotonic()
    with _lock:
        _cleanup_locked(now)
        if len(_failures.get(actor.id, [])) >= 5:
            raise RateLimited("비밀번호 금고 인증을 여러 번 실패했습니다. 5분 후 다시 시도하십시오.")

    if not actor.password_hash or not verify_password(password or "", actor.password_hash):
        with _lock:
            _failures.setdefault(actor.id, []).append(time.monotonic())
        record(db, action=actions.CREDENTIAL_VAULT_DENIED, ctx=ctx, user=actor,
               resource_type="CREDENTIAL", result="FAILURE",
               detail={"reason": "password_mismatch"})
        db.commit()  # 실패 예외가 감사 증적을 취소하지 않도록 선반영
        raise Forbidden("본인 비밀번호가 일치하지 않습니다.")

    ttl, max_minutes = _minutes(db)
    with _lock:
        now = time.monotonic()
        _cleanup_locked(now)
        # 이전 열람 토큰은 버리고 새 세션 하나만 활성화한다.
        for key, state in list(_sessions.items()):
            if state.user_id == actor.id:
                del _sessions[key]
        token = secrets.token_urlsafe(32)
        fp = _fingerprint(actor)
        ip, agent = _identity(ctx)
        max_at = now + max_minutes * 60
        expires_at = min(now + ttl * 60, max_at)
        _sessions[_hash(token)] = VaultSession(actor.id, fp, ip, agent, expires_at, max_at)
        if len(_sessions) > _MAX_SESSIONS:
            # 끝나는 시각이 가장 이른 것부터 버린다. 지금 만든 세션은 남는다.
            for key, _ in sorted(_sessions.items(), key=lambda kv: kv[1].expires_at
                                 )[:len(_sessions) - _MAX_SESSIONS]:
                _sessions.pop(key, None)
        _failures.pop(actor.id, None)
    record(db, action=actions.CREDENTIAL_VAULT_UNLOCK, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", detail={"expires_in_seconds": int(expires_at-now),
                                              "max_seconds": max_minutes*60})
    return {"token": token, "expires_in_seconds": max(1,int(expires_at-now)),
            "remaining_absolute_seconds": int(max_at-now)}


def _get(actor: User, token: str, ctx: RequestContext | None) -> VaultSession:
    if not token or len(token) > 128:
        raise Forbidden("비밀번호 금고를 먼저 잠금 해제하십시오.")
    with _lock:
        now = time.monotonic()
        _cleanup_locked(now)
        state = _sessions.get(_hash(token))
        ip, agent = _identity(ctx)
        if (state is None or state.user_id != actor.id or
                state.hash_fingerprint != _fingerprint(actor) or
                state.client_ip != ip or state.user_agent != agent):
            raise Forbidden("열람 시간이 종료됐거나 인증 정보가 변경됐습니다.")
        return state


def status(actor: User, token: str, ctx: RequestContext | None) -> dict:
    with _lock:
        state = _get(actor, token, ctx)
        now = time.monotonic()
        return {"expires_in_seconds": max(0,int(state.expires_at-now)),
                "remaining_absolute_seconds": max(0,int(state.max_expires_at-now))}


def extend(db: Session, actor: User, token: str,
           ctx: RequestContext | None) -> dict:
    ttl, _ = _minutes(db)
    with _lock:
        state = _get(actor, token, ctx)
        now = time.monotonic()
        # 만료되거나 최대 유지 시각이 지난 세션은 연장 불가.
        state.expires_at = min(state.max_expires_at, now + ttl*60)
        remaining = max(0, int(state.expires_at-now))
    record(db, action=actions.CREDENTIAL_VAULT_EXTEND, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", detail={"seconds": remaining})
    return {"expires_in_seconds": remaining,
            "remaining_absolute_seconds": max(0,int(state.max_expires_at-now))}


def lock(actor: User, token: str | None, ctx: RequestContext | None,
         db: Session | None = None) -> None:
    """'지금 잠그기'. 토큰을 잃어버렸어도 그 사람의 열람 세션은 모두 닫는다 —
    화면이 잠겼다고 말하면서 서버에 세션이 남아 있으면 안 된다."""
    with _lock:
        if token:
            state = _sessions.get(_hash(token))
            if state and state.user_id == actor.id:
                _sessions.pop(_hash(token), None)
        else:
            for key, state in list(_sessions.items()):
                if state.user_id == actor.id:
                    _sessions.pop(key, None)
    if db is not None:
        record(db, action=actions.CREDENTIAL_VAULT_LOCK, ctx=ctx, user=actor,
               resource_type="CREDENTIAL")


def revoke_user(user_id: int) -> None:
    with _lock:
        for key, state in list(_sessions.items()):
            if state.user_id == user_id:
                _sessions.pop(key, None)
