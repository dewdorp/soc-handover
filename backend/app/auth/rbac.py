"""RBAC 권한 매트릭스. docs/API.md §10 이 단일 출처이며 이 파일이 그 구현이다.

행 단위(소유권) 검사는 서비스 계층에서 수행한다. 여기서는 기능 단위 권한만 다룬다.
"""
from __future__ import annotations

from typing import Final

ROLE_ADMIN: Final = "ADMIN"
ROLE_MANAGER: Final = "MANAGER"
ROLE_ANALYST: Final = "ANALYST"
ALL_ROLES: Final = (ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)

# 모든 로그인 사용자에게 공통으로 부여되는 권한
_BASE: Final[frozenset[str]] = frozenset({
    "handover:read",
    "handover:create",
    "handover:update_own",   # 본인 작성 또는 담당 건
    "handover:star",
    "handover:comment",
    "handover:attach",
    "ack:write",
    "shift:transfer",
    "task:read", "task:create", "task:update", "task:delete_own",
    "schedule:read", "schedule:create", "schedule:update_own",
    "savedview:personal",
    "export:run",
    "notification:read",
    "audit:read_self",
    "search:use",
    # 장비 비밀번호: 등록은 누구나, 보기는 범위(SHARED/PERSONAL)와 본인 확인으로 가른다
    "credential:read",
    "credential:create",
    "credential:update_own",
})

_MANAGER_EXTRA: Final[frozenset[str]] = frozenset({
    "handover:update_any",
    "handover:delete",
    "handover:pin",
    "handover:read_deleted",
    "task:update_any", "task:delete_any",
    "schedule:update_any",
    "savedview:shared",
    "import:run",
    "audit:read_all",
    "user:read",
    "company:manage",
    "credential:update_any",
    "stats:read_all",
})

_ADMIN_EXTRA: Final[frozenset[str]] = frozenset({
    "handover:undelete",
    "import:rollback",
    "user:manage",
    "role:change",
    "settings:manage",
    # 그룹을 만들고 사람을 넣는 권한. 다른 그룹 업무의 **원문을 읽는 권한은 아니다**.
    "group:manage",
    "status:manage",
    "shift:manage",
    "system:maintain",
})

PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    ROLE_ANALYST: _BASE,
    ROLE_MANAGER: _BASE | _MANAGER_EXTRA,
    ROLE_ADMIN: _BASE | _MANAGER_EXTRA | _ADMIN_EXTRA,
}


def permissions_for(role_code: str | None) -> frozenset[str]:
    return PERMISSIONS.get((role_code or "").upper(), frozenset())


def has_permission(role_code: str | None, permission: str) -> bool:
    return permission in permissions_for(role_code)


def can_edit_handover(*, role_code: str, user_id: int,
                      creator_id: int | None, assignee_id: int | None) -> bool:
    """ANALYST 는 본인이 작성했거나 담당자인 건만 수정할 수 있다."""
    if has_permission(role_code, "handover:update_any"):
        return True
    if not has_permission(role_code, "handover:update_own"):
        return False
    return user_id in {creator_id, assignee_id}
