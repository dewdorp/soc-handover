"""시스템/기능 플래그 라우터. 프론트가 메뉴 구성을 결정하는 근거를 제공한다."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.actions import BACKUP, RESTORE
from app.audit.recorder import record
from app.auth.deps import require_password_changed
from app.core.config import settings
from app.core.context import RequestContext, get_context
from app.core.db import dialect_name, get_db
from app.core.errors import Forbidden, ValidationFailed
from app.models.common import SystemSetting
from app.models.user import User
from app.services import settings_service

# /health 는 익명, /audit/system-event 는 loopback 전용이므로 라우터 전체를 묶지 않고
# 인증이 필요한 엔드포인트에만 비밀번호 변경 게이트를 건다.
router = APIRouter(tags=["system"])

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
SYSTEM_EVENT_ACTIONS = {BACKUP, RESTORE}


class SystemEvent(BaseModel):
    action: str = Field(max_length=40)
    detail: dict | None = None
    result: str = Field(default="SUCCESS", pattern=r"^(SUCCESS|FAILURE)$")
    error_message: str | None = None


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """인증 없이 호출 가능한 헬스체크(start.ps1 / status.ps1 이 사용)."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - 장애 경로
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "database": dialect_name(),
        "database_ok": db_ok,
    }


@router.post("/audit/system-event", status_code=201)
def system_event(payload: SystemEvent, request: Request, db: Session = Depends(get_db),
                 ctx: RequestContext = Depends(get_context)):
    """backup.ps1 / restore.ps1 이 운영 작업을 감사에 남기기 위한 로컬 전용 엔드포인트.

    서버와 같은 장비(loopback)에서만 호출할 수 있고, 허용된 Action 만 기록한다.
    """
    client = request.client.host if request.client else ""
    if client not in LOOPBACK:
        raise Forbidden("로컬에서만 호출할 수 있습니다.")
    if payload.action not in SYSTEM_EVENT_ACTIONS:
        raise ValidationFailed(f"허용되지 않은 시스템 이벤트입니다: {payload.action}")

    record(db, action=payload.action, ctx=ctx, username="system", role_code="SYSTEM",
           resource_type="SYSTEM", resource_id=payload.action.lower(),
           result=payload.result, error_message=payload.error_message,
           detail=payload.detail)
    return {"recorded": True, "action": payload.action}


@router.get("/settings/features")
def features(db: Session = Depends(get_db), _: User = Depends(require_password_changed)):
    """AI 활성 여부 등 화면 구성에 필요한 플래그.

    AI가 꺼져 있으면 프론트는 AI 라우트를 아예 등록하지 않는다(§54).
    """
    ai = settings_service.ai_flags(db)
    return {
        "ai_enabled": ai["enabled"],
        "ai": ai,
        "attachment": {
            "allowed_ext": settings_service.get_value(db, "attachment.allowed_ext"),
            "max_size_mb": settings_service.get_value(db, "attachment.max_size_mb"),
        },
        "ack": {"reack_fields": settings_service.get_value(db, "ack.reack_fields")},
        "export": {"max_rows": settings.EXPORT_MAX_ROWS},
        "page": {"default_size": settings.DEFAULT_PAGE_SIZE, "max_size": settings.MAX_PAGE_SIZE},
        "database": dialect_name(),
        #: SQLite 는 개발/평가용이다. 운영 화면에 경고 배너를 띄우기 위한 플래그(ASSUMPTIONS A-01)
        "database_warning": (
            "개발/평가용 SQLite로 동작 중입니다. 운영에는 PostgreSQL을 사용하십시오."
            if settings.is_sqlite else None
        ),
    }


@router.get("/settings")
def list_settings(db: Session = Depends(get_db), user: User = Depends(require_password_changed)):
    from app.auth.rbac import has_permission
    from app.core.errors import Forbidden
    if not has_permission(user.role_code, "settings:manage"):
        raise Forbidden()
    rows = db.scalars(select(SystemSetting).order_by(SystemSetting.category,
                                                     SystemSetting.key)).all()
    return [
        {
            "key": r.key,
            "value": "***" if r.is_secret else r.value,
            "category": r.category,
            "description": r.description,
            "is_secret": r.is_secret,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]
