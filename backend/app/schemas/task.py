"""할일(Task) · 체크리스트 · 댓글 · 내 업무 스키마 (API.md §5).

할일은 인수인계(사실 기록)와 분리된 '해야 할 일'이다(§37). 인수인계처럼 수정 요청에
expected_version 이 필수다 — 보드에서 같은 카드를 두 사람이 동시에 옮겨도 한쪽이 조용히
사라지지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.auth import UserBrief
from app.schemas.reference import CompanyOut, PriorityOut

TaskStatus = Literal["TODO", "IN_PROGRESS", "WAITING", "DONE", "CANCELED"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    status: TaskStatus = "TODO"
    priority_code: str = Field(default="NORMAL", max_length=20)
    assignee_id: int | None = None          # 비우면 만든 사람
    company_id: int | None = None
    handover_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    checklist: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("마감일이 시작일보다 빠를 수 없습니다.")
        return self


class QuickAddRequest(BaseModel):
    """인수인계에서 바로 만들기(FR-D-06). 비운 칸은 인수인계에서 채운다."""
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    priority_code: str | None = Field(default=None, max_length=20)
    assignee_id: int | None = None
    due_date: date | None = None
    checklist: list[str] = Field(default_factory=list, max_length=50)


class TaskUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    status: TaskStatus | None = None
    priority_code: str | None = Field(default=None, max_length=20)
    assignee_id: int | None = None
    company_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None

    def changes(self) -> dict[str, Any]:
        data = self.model_dump(exclude_unset=True)
        data.pop("expected_version", None)
        return data

    @model_validator(mode="after")
    def _require_something(self):
        if not self.changes():
            raise ValueError("변경할 필드를 하나 이상 지정하십시오.")
        if "title" in self.changes() and self.title is None:
            raise ValueError("제목은 비울 수 없습니다.")
        return self


class TaskMove(BaseModel):
    """보드 끌어놓기(FR-D-05).

    위치는 '어느 카드 바로 뒤'로 받는다(after_id, 없으면 맨 위). 화면이 담당자 등으로
    걸러진 보드를 보여줘도 전체 칸의 순서가 어긋나지 않는다 — 몇 번째 자리로 받으면
    걸러진 목록의 번호와 실제 칸의 번호가 달라진다.
    """
    expected_version: int = Field(ge=1)
    status: Literal["TODO", "IN_PROGRESS", "WAITING", "DONE"]
    after_id: int | None = None


class DeleteTaskRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ChecklistCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChecklistUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_done: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=32_000)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)


class TaskSearchRequest(BaseModel):
    """할일 목록 조건. 인수인계 DSL 처럼 열린 필드 목록이 아니라 정해진 조건만 받는다."""
    q: str | None = Field(default=None, max_length=200)
    status: list[TaskStatus] | None = None
    include_closed: bool = False            # status 를 지정하지 않았을 때 완료·취소도 볼지
    assignee: Literal["me", "all", "unassigned"] | int = "all"
    created_by_me: bool = False
    company_id: int | None = None
    handover_id: int | None = None
    due: Literal["overdue", "today", "this_week", "none"] | None = None
    sort: Literal["due_date", "updated_at", "priority", "created_at"] = "due_date"
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)


# --------------------------------------------------------------------------- 출력

class ChecklistOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    title: str
    is_done: bool
    done_at: datetime | None
    done_by: int | None
    sort_order: int


class HandoverRef(BaseModel):
    id: int
    title: str
    is_deleted: bool = False


class TaskOut(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    priority: PriorityOut | None
    assignee: UserBrief | None
    creator: UserBrief | None
    company: CompanyOut | None
    handover: HandoverRef | None
    start_date: date | None
    due_date: date | None
    completed_at: datetime | None
    board_order: int
    version_no: int
    is_overdue: bool
    checklist_total: int
    checklist_done: int
    comment_count: int
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class TaskDetail(TaskOut):
    checklists: list[ChecklistOut]


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    size: int


class BoardOut(BaseModel):
    columns: dict[str, list[TaskOut]]
    counts: dict[str, int]
    done_since: date                       # 완료 칸은 이 날짜 이후 완료분만


class CommentOut(BaseModel):
    id: int
    body: str
    author_id: int | None
    author: str | None
    created_at: datetime
    can_delete: bool


# --------------------------------------------------------------------------- 내 업무

MyWorkBucket = Literal["all", "today", "overdue", "this_week", "upcoming",
                       "need_ack", "waiting", "done"]
MyWorkSource = Literal["all", "task", "handover", "ack", "schedule"]


class MyWorkItem(BaseModel):
    kind: Literal["TASK", "HANDOVER", "ACK", "SCHEDULE"]
    id: int                                 # TASK → task id, SCHEDULE → schedule id, 나머지 → handover id
    title: str
    company: str | None
    due: date | None                        # 할일 마감 / 인수인계 수행일
    status: str | None                      # 표시용 이름
    status_code: str | None
    priority_code: str | None
    is_overdue: bool
    handover_id: int | None                 # 연결된 인수인계(할일) / 자기 자신
    ack_state: str | None = None
    from_user: str | None = None            # ACK: 넘겨준 사람
    session_id: int | None = None
    checklist_total: int | None = None
    checklist_done: int | None = None
    start_at: datetime | None = None        # SCHEDULE: 이 회차의 시작
    end_at: datetime | None = None
    all_day: bool | None = None
    recurring: bool | None = None


class MyWorkOut(BaseModel):
    bucket: str
    source: str
    today: date
    week_end: date
    counts: dict[str, int]
    items: list[MyWorkItem]
