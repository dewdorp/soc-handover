"""일정 · 달력 라우터 (API.md §5, FR-E). 규칙은 services/schedule_service.py 에 있다."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import ValidationFailed
from app.models.user import User
from app.schemas.schedule import (CalendarOut, DeleteScheduleRequest, MyScheduleOut,
                                  ReminderOut, ReminderUpdate, ScheduleCreate, ScheduleMove,
                                  ScheduleOut, ScheduleUpdate)
from app.services import schedule_service as svc

router = APIRouter(tags=["schedules"], dependencies=[Depends(require_password_changed)])
LAYERS = {"schedule", "task", "handover"}


@router.get("/calendar", response_model=CalendarOut)
def calendar(start: datetime, end: datetime,
             layers: str = Query(default="schedule,task,handover", max_length=40),
             mine: bool = False, db: Session = Depends(get_db),
             actor: User = Depends(require("schedule:read"))):
    """일정 + 할일 마감 + 인수인계 수행일(레이어). 기간은 최대 100일, 끝은 포함하지 않는다."""
    picked = {x.strip() for x in layers.split(",") if x.strip()}
    if not picked or picked - LAYERS:
        raise ValidationFailed("layers 는 schedule · task · handover 중에서 고릅니다.")
    return svc.calendar(db, actor, start, end, picked, mine)


@router.get("/schedules/mine", response_model=list[MyScheduleOut])
def my_schedules(days: int = Query(default=7, ge=1, le=92),
                 per_series: int = Query(default=3, ge=1, le=20),
                 db: Session = Depends(get_db),
                 actor: User = Depends(require("schedule:read"))):
    """'내 일정' — 오늘부터 N일. 반복 일정은 앞의 몇 회차만 보여 주고 나머지는 숫자로 센다."""
    return svc.mine_upcoming(db, actor, days=days, per_series=per_series)


@router.put("/schedules/{schedule_id}/reminder", response_model=ReminderOut)
def set_reminder(schedule_id: int, payload: ReminderUpdate, db: Session = Depends(get_db),
                 actor: User = Depends(require("schedule:read")),
                 ctx: RequestContext = Depends(get_context)):
    """'내 알림' — 사람마다 따로. null 이면 끄기, 0 이면 시작할 때, 그 밖은 N분 전."""
    value = svc.set_reminder(db, actor, schedule_id, payload.minutes_before)
    return {"schedule_id": schedule_id, "minutes_before": value}


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(payload: ScheduleCreate, db: Session = Depends(get_db),
                    actor: User = Depends(require("schedule:create")),
                    ctx: RequestContext = Depends(get_context)):
    return svc.to_out(actor, svc.create(db, actor, payload.model_dump(), ctx))


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require("schedule:read"))):
    return svc.to_out(actor, svc.get_or_404(db, schedule_id))


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int, payload: ScheduleUpdate, db: Session = Depends(get_db),
                    actor: User = Depends(require("schedule:update_own")),
                    ctx: RequestContext = Depends(get_context)):
    s = svc.update(db, actor, schedule_id, payload.expected_version, payload.changes(), ctx)
    return svc.to_out(actor, s)


@router.patch("/schedules/{schedule_id}/move", response_model=ScheduleOut)
def move_schedule(schedule_id: int, payload: ScheduleMove, db: Session = Depends(get_db),
                  actor: User = Depends(require("schedule:update_own")),
                  ctx: RequestContext = Depends(get_context)):
    s = svc.move(db, actor, schedule_id, payload.expected_version, payload.start_at, payload.end_at, ctx)
    return svc.to_out(actor, s)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: int, payload: DeleteScheduleRequest | None = Body(default=None),
                    db: Session = Depends(get_db),
                    actor: User = Depends(require("schedule:update_own")),
                    ctx: RequestContext = Depends(get_context)):
    svc.delete(db, actor, schedule_id, payload.reason if payload else None, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/handovers/{handover_id}/schedules", response_model=list[ScheduleOut])
def handover_schedules(handover_id: int, db: Session = Depends(get_db),
                       actor: User = Depends(require("schedule:read"))):
    return [svc.to_out(actor, s) for s in svc.for_handover(db, handover_id)]


@router.get("/tasks/{task_id}/schedules", response_model=list[ScheduleOut])
def task_schedules(task_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("schedule:read"))):
    return [svc.to_out(actor, s) for s in svc.for_task(db, task_id)]
