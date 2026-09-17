"""Local 계정 인증. 잠금/실패 카운트도 여기서 관리한다(SECURITY §1.3)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.providers.base import AuthResult, ExternalUser
from app.core.config import settings
from app.core.security import hash_password, needs_rehash, verify_password
from app.core.time import now
from app.models.user import User


class LocalAuthProvider:
    name = "local"

    def __init__(self, db: Session):
        self.db = db

    def _get(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def lookup(self, username: str) -> ExternalUser | None:
        u = self._get(username)
        if not u:
            return None
        return ExternalUser(username=u.username, display_name=u.display_name,
                            email=u.email, team=u.team)

    def authenticate(self, username: str, password: str) -> AuthResult:
        user = self._get(username)
        if user is None:
            return AuthResult(ok=False, reason="NO_USER")
        if not user.is_active:
            return AuthResult(ok=False, reason="INACTIVE")
        if user.locked_until and user.locked_until > now():
            return AuthResult(ok=False, reason="LOCKED")

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILS:
                minutes = settings.LOGIN_LOCK_MINUTES
                if user.failed_login_count >= settings.LOGIN_MAX_FAILS * 2:
                    minutes *= 6
                user.locked_until = now() + timedelta(minutes=minutes)
            self.db.flush()
            return AuthResult(ok=False, reason="BAD_PASSWORD")

        # 성공
        if user.password_hash and needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now()
        self.db.flush()
        return AuthResult(ok=True, user_id=user.id)
