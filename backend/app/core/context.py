"""요청 컨텍스트. 감사 로그가 필요로 하는 IP/UA/요청ID를 한 곳에서 제공한다."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request


@dataclass(slots=True)
class RequestContext:
    request_id: str
    client_ip: str | None
    user_agent: str | None

    @classmethod
    def from_request(cls, request: Request) -> "RequestContext":
        # 프록시 미사용 전제. X-Forwarded-For 는 신뢰하지 않는다(SECURITY §5).
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
        return cls(request_id=rid, client_ip=ip, user_agent=(ua or "")[:400] or None)


def get_context(request: Request) -> RequestContext:
    ctx = getattr(request.state, "ctx", None)
    if ctx is None:
        ctx = RequestContext.from_request(request)
        request.state.ctx = ctx
    return ctx
