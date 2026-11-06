"""일정 · 달력 스키마 (API.md §5, FR-E).

시각은 시간대가 붙은 ISO 8601 로 주고받는다. 시간대가 없으면 KST 로 본다.
끝(end_at)은 포함하지 않는다 — 하루 종일 일정 9/19 는 9/19 00:00 ~ 9/20 00:00.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.auth import UserBrief
from app.schemas.reference import CompanyOut

EventType = Literal["GENERAL", "WORK_PLANNED", "INSPECTION", "MEETING", "SECURITY_WORK", "RECURRING"]
COLOR = r"^#[0-9a-fA-F]{6}$"


class ScheduleCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)   # 연결 대상이 있으면 비워도 된다
    description: str | None = Field(default=None, max_length=20_000)
    event_type: EventType = "GENERAL"
    start_at: datetime
    end_at: datetime | None = None                            # 비우면 1시간(하루 종일이면 그날 하루)
    is_all_day: bool = False
    company_id: int | None = None
    handover_id: int | None = None
    task_id: int | None = None
    owner_id: int | None = None                                # 비우면 만든 사람
    recurrence_rule: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, pattern=COLOR)


class ScheduleUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    event_type: EventType | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_all_day: bool | None = None
    company_id: int | None = None
    owner_id: int | None = None
    recurrence_rule: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, pattern=COLOR)

    def changes(self) -> dict[str, Any]:
        data = self.model_dump(exclude_unset=True)
        data.pop("expected_version", None)
        return data

    @model_validator(mode="after")
    def _require_something(self):
        changes = self.changes()
        if not changes:
            raise ValueError("변경할 필드를 하나 이상 지정하십시오.")
        for key in ("title", "event_type", "start_at", "end_at", "is_all_day"):
            if key in changes and changes[key] is None:
                raise ValueError(f"{key} 는 비울 수 없습니다.")
        return self


class ScheduleMove(BaseModel):
    """달력 끌어놓기(FR-E-04). end_at 을 비우면 길이를 유지한다."""
    expected_version: int = Field(ge=1)
    start_at: datetime
    end_at: datetime | None = None


class DeleteScheduleRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- 출력

class LinkRef(BaseModel):
    id: int
    title: str
    is_deleted: bool = False


class ScheduleOut(BaseModel):
    id: int
    title: str
    description: str | None
    event_type: str
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    company: CompanyOut | None
    handover: LinkRef | None
    task: LinkRef | None
    owner: UserBrief | None
    creator: UserBrief | None
    recurrence_rule: str | None
    recurrence_text: str | None
    series_end: datetime | None          # 반복이 끝나는 때(끝이 없으면 null)
    color: str | None
    version_no: int
    can_edit: bool
    created_at: datetime
    updated_at: datetime


CalendarLayer = Literal["schedule", "task", "handover"]


class CalendarEvent(BaseModel):
    key: str                             # 화면 목록 키 — 반복 회차마다 다르다
    kind: Literal["SCHEDULE", "TASK", "HANDOVER"]
    id: int
    title: str
    start: datetime | None = None        # SCHEDULE
    end: datetime | None = None
    day: date | None = None              # TASK 마감일 · HANDOVER 수행일(하루 종일)
    all_day: bool
    event_type: str | None = None
    color: str | None = None
    company: str | None = None
    status: str | None = None
    is_done: bool = False
    is_overdue: bool = False
    recurring: bool = False
    owner: str | None = None
    can_move: bool = False               # 끌어서 옮길 수 있나(반복이 아니고 고칠 수 있는 일정)
    version_no: int | None = None


class CalendarOut(BaseModel):
    start: datetime
    end: datetime
    events: list[CalendarEvent]
    truncated: bool


class ReminderUpdate(BaseModel):
    """null = 끄기 · 0 = 시작할 때 · 10/30 = N분 전 · 그 밖 = 직접 넣은 분."""
    minutes_before: int | None = Field(default=None, ge=0, le=7 * 24 * 60)


class ReminderOut(BaseModel):
    schedule_id: int
    minutes_before: int | None = None


class MyScheduleOut(BaseModel):
    id: int
    title: str
    event_type: str
    start_at: datetime
    end_at: datetime
    is_all_day: bool = False
    company: str | None = None
    handover_id: int | None = None
    task_id: int | None = None
    recurrence_rule: str | None = None
    reminder_minutes: int | None = None
    #: 이 일정의 몇 번째 회차인가(1부터)
    occurrence_no: int = 1
    #: 첫 줄에만 — 보여 주지 않은 회차가 몇 번 더 있는가
    more_occurrences: int = 0


# --------------------------------------------------------------------------- 정기 점검
class InspectionOut(BaseModel):
    """그 날 돌아야 하는 점검 한 건과 완료 여부."""
    schedule_id: int
    title: str
    occurrence_date: date
    start_at: datetime
    company: str | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    recurrence_text: str | None = None
    is_done: bool = False
    done_by_name: str | None = None
    done_at: datetime | None = None
    note: str | None = None
    is_mine: bool = False


class InspectionDone(BaseModel):
    occurrence_date: date
    note: str | None = Field(default=None, max_length=300)
