"""RBAC 매트릭스 검증. docs/API.md §10 표를 그대로 테스트한다."""
from __future__ import annotations

import pytest

from app.auth.rbac import (ROLE_ADMIN, ROLE_ANALYST, ROLE_MANAGER, can_edit_handover,
                           has_permission, permissions_for)

# (permission, ANALYST, MANAGER, ADMIN)
MATRIX = [
    ("handover:read",          True,  True,  True),
    ("handover:create",        True,  True,  True),
    ("handover:update_own",    True,  True,  True),
    ("handover:update_any",    False, True,  True),
    ("handover:delete",        False, True,  True),
    ("handover:undelete",      False, False, True),
    ("handover:pin",           False, True,  True),
    ("handover:read_deleted",  False, True,  True),
    ("ack:write",              True,  True,  True),
    ("shift:transfer",         True,  True,  True),
    ("savedview:personal",     True,  True,  True),
    ("savedview:shared",       False, True,  True),
    ("import:run",             False, True,  True),
    ("import:rollback",        False, False, True),
    ("audit:read_all",         False, True,  True),
    ("user:manage",            False, False, True),
    ("role:change",            False, False, True),
    ("settings:manage",        False, False, True),
    ("ai:manage",              False, False, False),   # AI 는 범위에서 뺐다
    ("export:run",             True,  True,  True),
]


@pytest.mark.parametrize("perm,analyst,manager,admin", MATRIX)
def test_permission_matrix(perm, analyst, manager, admin):
    assert has_permission(ROLE_ANALYST, perm) is analyst
    assert has_permission(ROLE_MANAGER, perm) is manager
    assert has_permission(ROLE_ADMIN, perm) is admin


def test_roles_are_cumulative():
    assert permissions_for(ROLE_ANALYST) < permissions_for(ROLE_MANAGER)
    assert permissions_for(ROLE_MANAGER) < permissions_for(ROLE_ADMIN)


def test_unknown_role_has_nothing():
    assert permissions_for("GUEST") == frozenset()
    assert permissions_for(None) == frozenset()
    assert not has_permission("GUEST", "handover:read")


class TestHandoverEditOwnership:
    def test_analyst_can_edit_own(self):
        assert can_edit_handover(role_code=ROLE_ANALYST, user_id=5,
                                 creator_id=5, assignee_id=None)

    def test_analyst_can_edit_assigned(self):
        assert can_edit_handover(role_code=ROLE_ANALYST, user_id=5,
                                 creator_id=9, assignee_id=5)

    def test_analyst_cannot_edit_others(self):
        assert not can_edit_handover(role_code=ROLE_ANALYST, user_id=5,
                                     creator_id=9, assignee_id=7)

    def test_manager_can_edit_any(self):
        assert can_edit_handover(role_code=ROLE_MANAGER, user_id=5,
                                 creator_id=9, assignee_id=7)

    def test_admin_can_edit_any(self):
        assert can_edit_handover(role_code=ROLE_ADMIN, user_id=1,
                                 creator_id=9, assignee_id=7)
