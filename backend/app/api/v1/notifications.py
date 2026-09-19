"""알림 라우터 (API.md §8). 본인 알림만 보고 읽음 처리한다."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.db import get_db
from app.core.errors import NotFound
from app.models.user import User
from app.schemas.shift import NotificationOut
from app.services import notification_service as svc

router = APIRouter(prefix="/notifications", tags=["notifications"],
                   dependencies=[Depends(require_password_changed)])


@router.get("", response_model=list[NotificationOut])
def list_notifications(unread: bool = False, limit: int = 50, db: Session = Depends(get_db),
                       actor: User = Depends(require("notification:read"))):
    return svc.list_for(db, actor.id, unread_only=unread, limit=min(limit, 200))


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db),
                 actor: User = Depends(require("notification:read"))):
    return {"unread": svc.unread_count(db, actor.id)}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db),
             actor: User = Depends(require("notification:read"))):
    return {"read": svc.mark_all_read(db, actor.id)}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(notification_id: int, db: Session = Depends(get_db),
             actor: User = Depends(require("notification:read"))):
    # 남의 알림이면 존재 여부를 드러내지 않는다
    if not svc.mark_read(db, actor.id, notification_id):
        raise NotFound("알림을 찾을 수 없거나 이미 읽었습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
