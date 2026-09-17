"""인증 Provider 인터페이스. 향후 LDAP/AD 연동을 위해 인증과 인가를 분리한다(§68)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class ExternalUser:
    username: str
    display_name: str
    email: str | None = None
    team: str | None = None
    external_id: str | None = None


@dataclass(slots=True)
class AuthResult:
    ok: bool
    user_id: int | None = None
    reason: str | None = None          # 내부 기록용(사용자에게 노출하지 않는다)
    external: ExternalUser | None = None


@runtime_checkable
class AuthProvider(Protocol):
    name: str

    def authenticate(self, username: str, password: str) -> AuthResult: ...

    def lookup(self, username: str) -> ExternalUser | None: ...
