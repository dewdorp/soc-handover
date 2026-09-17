"""도메인 예외 → HTTP 응답 변환. 사용자에게 스택트레이스를 노출하지 않는다."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("app.error")


class AppError(Exception):
    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "처리 중 오류가 발생했습니다."

    def __init__(self, message: str | None = None, detail: dict[str, Any] | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.detail = detail or {}


class NotFound(AppError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "대상을 찾을 수 없습니다."


class Unauthorized(AppError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "로그인이 필요합니다."


class Forbidden(AppError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    message = "권한이 없습니다."


class ValidationFailed(AppError):
    code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "입력값이 올바르지 않습니다."


class Conflict(AppError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT
    message = "현재 상태와 충돌합니다."


class VersionConflict(Conflict):
    """Optimistic Lock 충돌(§26). 조용히 덮어쓰지 않는다."""
    code = "version_conflict"
    message = "다른 사용자가 해당 인수인계를 수정했습니다."


class RateLimited(AppError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "요청이 너무 많습니다. 잠시 후 다시 시도하십시오."


class FeatureDisabled(AppError):
    """비활성 기능(AI 등)은 존재를 드러내지 않기 위해 404로 응답한다."""
    code = "feature_disabled"
    status_code = status.HTTP_404_NOT_FOUND
    message = "사용할 수 없는 기능입니다."


def _payload(code: str, message: str, detail: dict, request_id: str | None) -> dict:
    body = {"error": code, "message": message, "detail": detail}
    if request_id:
        body["request_id"] = request_id
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        rid = getattr(request.state, "request_id", None)
        if exc.status_code >= 500:
            log.exception("request_id=%s %s", rid, exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.detail, rid),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None)
        fields = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "reason": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", "입력값이 올바르지 않습니다.", {"fields": fields}, rid),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover - 방어적
        rid = getattr(request.state, "request_id", None)
        log.exception("unhandled request_id=%s", rid)
        return JSONResponse(
            status_code=500,
            content=_payload("internal_error", "처리 중 오류가 발생했습니다.", {}, rid),
        )
