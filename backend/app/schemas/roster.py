"""근무표 요청/응답 스키마."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TeamMemberOut(BaseModel):
    user_id: int
    display_name: str
    username: str
    is_leader: bool = False


class TeamOut(BaseModel):
    id: int
    code: str
    name: str
    phase_days: int
    is_active: bool
    sort_order: int
    members: list[TeamMemberOut] = []


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    phase_days: int | None = Field(default=None, ge=0, le=63)
    is_active: bool | None = None


class MembersUpdate(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=20)
    leader_id: int | None = None


class ShiftChange(BaseModel):
    id: int
    kind: str
    off_user_id: int
    off_user_name: str | None = None
    on_user_id: int | None = None
    on_user_name: str | None = None
    reason: str | None = None


class ShiftStaffing(BaseModel):
    work_date: date
    shift_code: str
    shift_label: str
    team_id: int | None = None
    team_code: str | None = None
    team_name: str | None = None
    planned_user_ids: list[int] = []
    planned_names: list[str] = []
    actual_user_ids: list[int] = []
    actual_names: list[str] = []
    changes: list[ShiftChange] = []
    expected: int
    short_by: int
    is_short: bool
    is_mine: bool = False
    was_mine_planned: bool = False


class RosterDay(BaseModel):
    day: date
    shifts: list[ShiftStaffing] = []
    off_team_codes: list[str] = []


class RosterCalendar(BaseModel):
    start: date
    end: date
    days: list[RosterDay] = []
    cycle_days: int
    pattern: str
    epoch: date


class MyShift(BaseModel):
    work_date: date
    shift_code: str
    shift_label: str
    team_code: str | None = None
    start_at: datetime
    end_at: datetime
    with_names: list[str] = []
    is_short: bool = False
    short_by: int = 0


class NextShiftOut(BaseModel):
    work_date: date
    shift_code: str
    shift_label: str
    team_code: str | None = None
    team_name: str | None = None
    user_ids: list[int] = []
    names: list[str] = []
    is_short: bool = False
    short_by: int = 0
    replaced: list[ShiftChange] = []


class OverrideCreate(BaseModel):
    """대근(on_user_id 있음) 또는 결원(없음)."""
    work_date: date
    shift_code: Literal["DAY", "NIGHT"]
    off_user_id: int
    on_user_id: int | None = None
    reason: str | None = Field(default=None, max_length=500)


class SwapSide(BaseModel):
    work_date: date
    shift_code: Literal["DAY", "NIGHT"]
    user_id: int


class SwapCreate(BaseModel):
    first: SwapSide
    second: SwapSide
    reason: str | None = Field(default=None, max_length=500)


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OverrideOut(BaseModel):
    id: int
    work_date: date
    shift_code: str
    shift_label: str
    kind: str
    off_user_id: int
    off_user_name: str | None = None
    on_user_id: int | None = None
    on_user_name: str | None = None
    reason: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    canceled_at: datetime | None = None
    cancel_reason: str | None = None
    pair_id: int | None = None


class CoverageProblem(BaseModel):
    day: date
    day_teams: list[str] = []
    night_teams: list[str] = []


class CoverageOut(BaseModel):
    start: date
    days: int
    ok: bool
    problems: list[CoverageProblem] = []
