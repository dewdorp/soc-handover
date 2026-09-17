"""감사 기록기. 서비스 계층에서 명시적으로 호출한다.

· 일반 행위: 기록 실패가 업무를 막지 않는다(경고 로그 + 카운터).
· 고위험 행위(CRITICAL_ACTIONS): 기록 실패 시 예외를 전파해 트랜잭션을 롤백시킨다.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.actions import CRITICAL_ACTIONS
from app.core.context import RequestContext
from app.core.time import now
from app.models.common import AuditLog

log = logging.getLogger("app.audit")

#: 값이 절대 기록되면 안 되는 필드(SECURITY §5)
MASKED_KEYS = frozenset({
    "password", "password_hash", "current", "new", "new_password", "token",
    "refresh_token", "access_token", "api_key", "llm_api_key", "secret", "secret_key",
})
_MASK = "***"
_MAX_TEXT = 2000

failure_count = 0  # 운영 점검용 카운터


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {
            k: (_MASK if k.lower() in MASKED_KEYS else _sanitize(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + f"...(총 {len(value)}자)"
    return value


def record(
    db: Session,
    *,
    action: str,
    ctx: RequestContext | None = None,
    user: Any = None,
    username: str | None = None,
    role_code: str | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    result: str = "SUCCESS",
    error_message: str | None = None,
    detail: dict | None = None,
) -> AuditLog | None:
    entry = AuditLog(
        event_uuid=uuid.uuid4().hex,
        occurred_at=now(),
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None) or username,
        role_code=getattr(user, "role_code", None) or role_code,
        client_ip=ctx.client_ip if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
        request_id=ctx.request_id if ctx else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        before_value=_sanitize(before) if before is not None else None,
        after_value=_sanitize(after) if after is not None else None,
        result=result,
        error_message=(error_message or "")[:2000] or None,
        detail=_sanitize(detail) if detail is not None else None,
    )
    try:
        db.add(entry)
        db.flush()
        return entry
    except Exception:
        global failure_count
        failure_count += 1
        log.exception("감사 기록 실패: action=%s resource=%s/%s",
                      action, resource_type, resource_id)
        if action in CRITICAL_ACTIONS:
            raise
        return None
