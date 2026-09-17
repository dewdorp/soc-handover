"""요청 컨텍스트 · 보안 헤더 · CSRF · Rate Limit 미들웨어."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.context import RequestContext
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, csrf_matches

log = logging.getLogger("app.access")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: 쿠키가 아직 없는 상태에서 호출되는 경로는 CSRF 검사 대상이 아니다.
CSRF_EXEMPT_PATHS = ("/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/health")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:16]
        request.state.request_id = rid
        request.state.ctx = RequestContext.from_request(request)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = rid
        if request.url.path.startswith("/api/"):
            log.info("%s %s %s %.1fms rid=%s", request.method, request.url.path,
                     response.status_code, elapsed, rid)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(), microphone=(), camera=()")
        if not request.url.path.startswith("/api/"):
            # 외부 CDN을 사용하지 않는다(오프라인 운영 요구와 일치)
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """더블 서브밋 쿠키 방식.

    쿠키로 인증된 상태 변경 요청만 검사한다(Authorization 헤더 기반 호출은 대상 아님).
    """

    async def dispatch(self, request: Request, call_next):
        if (request.method not in SAFE_METHODS
                and request.url.path.startswith("/api/")
                and not request.url.path.startswith(CSRF_EXEMPT_PATHS)
                and request.cookies.get(ACCESS_COOKIE)):
            if not csrf_matches(request.cookies.get(CSRF_COOKIE),
                                request.headers.get(CSRF_HEADER)):
                return JSONResponse(
                    status_code=403,
                    content={"error": "csrf_failed",
                             "message": "보안 토큰이 유효하지 않습니다. 페이지를 새로고침하십시오.",
                             "detail": {}},
                )
        return await call_next(request)


class RateLimiter:
    """단일 프로세스 전제의 인메모리 슬라이딩 윈도우(SECURITY §8).

    상태를 모듈 수준 객체에 두어 테스트에서 초기화/조정할 수 있게 한다.
    다중 워커로 확장하면 DB/파일 기반으로 승격해야 한다.
    """

    #: (경로 prefix, 최대 횟수, 윈도우 초)
    DEFAULT_RULES: tuple[tuple[str, int, int], ...] = (
        ("/api/v1/auth/login", 20, 300),
        ("/api/v1/export", 5, 60),
        ("/api/v1/import", 30, 60),
        ("/api/v1/ai", 10, 60),
    )

    def __init__(self) -> None:
        self.rules = self.DEFAULT_RULES
        self.enabled = True
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._hits.clear()
        self.rules = self.DEFAULT_RULES

    def check(self, path: str, client_ip: str) -> int | None:
        """허용이면 None, 차단이면 재시도까지 남은 초를 돌려준다."""
        if not self.enabled:
            return None
        rule = next((r for r in self.rules if path.startswith(r[0])), None)
        if rule is None:
            return None
        prefix, limit, window = rule
        bucket = self._hits[(prefix, client_ip)]
        now = time.monotonic()
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return int(window - (now - bucket[0])) + 1
        bucket.append(now)
        return None


limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        retry = limiter.check(request.url.path, ip)
        if retry is not None:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry)},
                content={"error": "rate_limited",
                         "message": "요청이 너무 많습니다. 잠시 후 다시 시도하십시오.",
                         "detail": {"retry_after_sec": retry}},
            )
        return await call_next(request)


def register_middleware(app: FastAPI) -> None:
    # 등록 역순으로 실행된다: RequestContext → Security → RateLimit → CSRF
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    if not settings.is_production:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.DEV_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id"],
        )
