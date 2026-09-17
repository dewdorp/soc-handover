"""비밀번호 해시 · JWT · CSRF 토큰. (SECURITY.md §1)"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

ALGORITHM = "HS256"
ACCESS_COOKIE = "soc_access"
REFRESH_COOKIE = "soc_refresh"
CSRF_COOKIE = "soc_csrf"
CSRF_HEADER = "X-CSRF-Token"


# ---------- password ----------

def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


PASSWORD_MIN_LEN = 12


def validate_password_policy(raw: str, username: str | None = None) -> list[str]:
    """정책 위반 사유 목록을 돌려준다(빈 목록이면 통과)."""
    problems: list[str] = []
    if len(raw) < PASSWORD_MIN_LEN:
        problems.append(f"{PASSWORD_MIN_LEN}자 이상이어야 합니다.")
    kinds = sum(
        bool(p.search(raw))
        for p in (re.compile(r"[a-z]"), re.compile(r"[A-Z]"), re.compile(r"\d"),
                  re.compile(r"[^A-Za-z0-9]"))
    )
    if kinds < 3:
        problems.append("영문 대문자·소문자·숫자·특수문자 중 3종 이상을 포함해야 합니다.")
    if username and len(username) >= 3 and username.lower() in raw.lower():
        problems.append("계정명을 포함할 수 없습니다.")
    return problems


# ---------- tokens ----------

def create_access_token(*, user_id: int, username: str, role: str,
                        minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes or settings.ACCESS_TOKEN_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "usr": username,
        "rol": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


def new_refresh_token() -> tuple[str, str]:
    """(원문, 해시). 원문은 쿠키로만 전달하고 DB에는 해시만 저장한다."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)
