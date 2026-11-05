"""근무표 라우터.

읽기는 모든 로그인 사용자(근무표는 함께 보는 것이다). **바꾸기는 shift:manage** —
조 편성·대근·맞교환은 근무 관리자와 관리자만 한다. 자기 근무를 자기가 빼는 일이
기록 없이 일어나면 인계 누락을 따질 근거가 사라진다.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import ValidationFailed
from app.core.time import today
from app.models.user import User
from app.schemas.roster import (CancelRequest, CoverageOut, MembersUpdate, MyShift,
                                NextShiftOut, OverrideCreate, OverrideOut, RosterCalendar,
                                ShiftStaffing, SwapCreate, TeamOut, TeamUpdate)
from app.services import roster_service as svc

router = APIRouter(prefix="/roster", tags=["roster"],
                   dependencies=[Depends(require_password_changed)])


def _team_out(team) -> dict:
    return {
        "id": team.id, "code": team.code, "name": team.name,
        "phase_days": team.phase_days, "is_active": team.is_active,
        "sort_order": team.sort_order,
        "members": [{"user_id": m.user_id,
                     "display_name": m.user.display_name if m.user else f"#{m.user_id}",
                     "username": m.user.username if m.user else "",
                     "is_leader": m.is_leader} for m in team.members],
    }


# --------------------------------------------------------------------------- 조 편성

@router.get("/teams", response_model=list[TeamOut])
def list_teams(include_inactive: bool = False, db: Session = Depends(get_db),
               _: User = Depends(require("schedule:read"))):
    return [_team_out(t) for t in svc.teams(db, include_inactive=include_inactive)]


@router.patch("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, payload: TeamUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require("shift:manage")),
                ctx: RequestContext = Depends(get_context)):
    team = svc.update_team(db, team_id, payload.model_dump(exclude_unset=True),
                           actor=actor, ctx=ctx)
    return _team_out(team)


@router.put("/teams/{team_id}/members", response_model=TeamOut)
def set_members(team_id: int, payload: MembersUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require("shift:manage")),
                ctx: RequestContext = Depends(get_context)):
    team = svc.set_members(db, team_id, payload.user_ids, leader_id=payload.leader_id,
                           actor=actor, ctx=ctx)
    return _team_out(team)


@router.get("/coverage", response_model=CoverageOut)
def coverage(start: date | None = None, days: int = Query(default=32, ge=1, le=120),
             db: Session = Depends(get_db), _: User = Depends(require("schedule:read"))):
    """주기가 맞물리는지 확인 — 매일 주간 1조 · 야간 1조여야 한다."""
    return svc.coverage_check(db, start or today(), days)


# --------------------------------------------------------------------------- 달력

@router.get("/calendar", response_model=RosterCalendar)
def calendar(start: date | None = None, end: date | None = None,
             view: str = Query(default="week", pattern="^(week|month)$"),
             mine: bool = False, db: Session = Depends(get_db),
             actor: User = Depends(require("schedule:read"))):
    """주 · 월 보기. start 를 비우면 이번 주(월요일) 또는 이번 달 1일부터."""
    if start is None:
        t0 = today()
        start = t0 - timedelta(days=t0.weekday()) if view == "week" else t0.replace(day=1)
    if end is None:
        if view == "week":
            end = start + timedelta(days=6)
        else:
            nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = nxt - timedelta(days=1)
    return svc.calendar(db, start, end, actor=actor, mine=mine)


@router.get("/day", response_model=list[ShiftStaffing])
def day(work_date: date | None = None, db: Session = Depends(get_db),
        actor: User = Depends(require("schedule:read"))):
    target = work_date or today()
    rows = []
    for code in ("DAY", "NIGHT"):
        row = svc.staffing(db, target, code)
        row["is_mine"] = actor.id in row["actual_user_ids"]
        row["was_mine_planned"] = actor.id in row["planned_user_ids"]
        rows.append(row)
    return rows


@router.get("/mine", response_model=list[MyShift])
def mine(days: int = Query(default=14, ge=1, le=92), db: Session = Depends(get_db),
         actor: User = Depends(require("schedule:read"))):
    return svc.my_upcoming(db, actor, days=days)


@router.get("/next-shift", response_model=NextShiftOut)
def next_shift(db: Session = Depends(get_db), actor: User = Depends(require("schedule:read"))):
    """다음 근무의 **실제** 근무자 — 교대 인계 화면이 인수자를 미리 채우는 데 쓴다."""
    return svc.suggested_recipients(db)


# --------------------------------------------------------------------------- 대근 · 맞교환

@router.get("/overrides", response_model=list[OverrideOut])
def list_overrides(start: date | None = None, end: date | None = None,
                   db: Session = Depends(get_db),
                   _: User = Depends(require("schedule:read"))):
    t0 = today()
    return svc.history(db, start=start or (t0 - timedelta(days=30)),
                       end=end or (t0 + timedelta(days=60)))


@router.post("/overrides", response_model=OverrideOut, status_code=status.HTTP_201_CREATED)
def create_override(payload: OverrideCreate, db: Session = Depends(get_db),
                    actor: User = Depends(require("shift:manage")),
                    ctx: RequestContext = Depends(get_context)):
    ovr = svc.substitute(db, work_date=payload.work_date, shift_code=payload.shift_code,
                         off_user_id=payload.off_user_id, on_user_id=payload.on_user_id,
                         reason=payload.reason, actor=actor, ctx=ctx)
    return svc._ovr_snapshot(ovr)


@router.post("/swaps", response_model=list[OverrideOut], status_code=status.HTTP_201_CREATED)
def create_swap(payload: SwapCreate, db: Session = Depends(get_db),
                actor: User = Depends(require("shift:manage")),
                ctx: RequestContext = Depends(get_context)):
    rows = svc.swap(db, first=payload.first.model_dump(), second=payload.second.model_dump(),
                    reason=payload.reason, actor=actor, ctx=ctx)
    return [svc._ovr_snapshot(r) for r in rows]


@router.post("/overrides/{override_id}/cancel", response_model=list[OverrideOut])
def cancel_override(override_id: int, payload: CancelRequest, db: Session = Depends(get_db),
                    actor: User = Depends(require("shift:manage")),
                    ctx: RequestContext = Depends(get_context)):
    rows = svc.cancel(db, override_id, reason=payload.reason, actor=actor, ctx=ctx)
    return [svc._ovr_snapshot(r) for r in rows]


@router.post("/epoch", response_model=CoverageOut)
def set_epoch(value: str = Query(min_length=10, max_length=10), db: Session = Depends(get_db),
              actor: User = Depends(require("shift:manage")),
              ctx: RequestContext = Depends(get_context)):
    """기준일을 바꾼다. 바꾼 뒤 주기가 맞물리는지 확인한 결과를 함께 돌려준다.

    맞물리지 않으면 저장하지 않는다 — 하루에 두 조가 겹치거나 빈 날이 생긴 근무표는
    근무표가 아니다.
    """
    from app.services import settings_service

    cleaned = settings_service.validate("roster.epoch_date", value)
    before = settings_service.get_value(db, "roster.epoch_date")
    settings_service.set_value(db, "roster.epoch_date", cleaned, actor=actor, ctx=ctx)
    result = svc.coverage_check(db, today(), 32)
    if not result["ok"]:
        settings_service.set_value(db, "roster.epoch_date", before, actor=actor, ctx=ctx)
        raise ValidationFailed("그 기준일로는 주기가 맞물리지 않습니다(주간 · 야간이 하루 1조씩이 아님).",
                               detail={"problems": [
                                   {"day": p["day"].isoformat(),
                                    "day_teams": p["day_teams"],
                                    "night_teams": p["night_teams"]} for p in result["problems"][:5]]})
    return result
