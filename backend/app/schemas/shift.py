"""교대 인수인계 · 알림 스키마."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.handover import HandoverListItem


class ShiftWindowOut(BaseModel):
    shift_id: int | None
    code: str
    name: str
    shift_date: date
    start_at: datetime
    end_at: datetime


class CockpitArea(BaseModel):
    label: str
    total: int
    #: 건수를 상한까지만 센 경우(그 이상이라는 뜻). 화면은 '9,999+' 처럼 보여 준다
    capped: bool = False
    #: 지금 보고 있는 영역만 채운다(나머지는 숫자만 — 50만 건에서 2초가 0.2초가 된다)
    items: list[HandoverListItem]
    #: 이 영역을 목록 화면에서 그대로 열 수 있는 DSL(숫자와 목록이 같다)
    request: dict[str, Any]


class CockpitOut(BaseModel):
    window: ShiftWindowOut
    next_window: ShiftWindowOut
    #: 목록을 채워 준 영역
    area: str
    areas: dict[str, CockpitArea]
    basket_handover_ids: list[int]


class SessionItemOut(BaseModel):
    item_id: int
    handover_id: int
    title: str
    company: str | None
    status: str | None
    status_category: str | None
    priority: str | None
    priority_code: str | None
    is_deleted: bool
    current_version_no: int | None
    version_no_at_transfer: int | None
    changed_since_transfer: bool
    item_note: str | None
    display_order: int
    is_carry_forward: bool
    carry_depth: int
    ack_state: str | None
    acked_version_no: int | None
    acked_at: datetime | None
    stale_reason: list[str] | None


class SessionOut(BaseModel):
    id: int
    status: str
    shift_date: date
    shift_id: int | None
    to_shift_id: int | None
    from_user_id: int
    from_user: str | None = None
    to_user_id: int | None
    to_user: str | None = None
    sent_at: datetime | None
    closed_at: datetime | None
    summary_note: str | None
    item_count: int
    acked_count: int = 0
    items: list[SessionItemOut] = []


class BasketOut(SessionOut):
    #: 이번에 열면서 직전 교대 미완료를 자동으로 담은 건수(화면 안내용)
    auto_added: int = 0
    carry_candidates: int = 0


class AddItemsRequest(BaseModel):
    handover_ids: list[int] = Field(min_length=1, max_length=500)
    item_note: str | None = Field(default=None, max_length=1000)


class ItemNoteRequest(BaseModel):
    item_note: str | None = Field(default=None, max_length=1000)


class BasketUpdate(BaseModel):
    to_user_id: int | None = None
    to_shift_id: int | None = None
    summary_note: str | None = Field(default=None, max_length=5000)
    #: 항목 id 를 원하는 순서대로
    order: list[int] | None = Field(default=None, max_length=500)


class SendRequest(BaseModel):
    to_user_id: int | None = None
    to_shift_id: int | None = None
    summary_note: str | None = Field(default=None, max_length=5000)


class InboxItem(BaseModel):
    handover_id: int
    title: str
    company: str | None
    status: str | None
    priority_code: str | None
    current_version_no: int
    state: str
    acked_version_no: int | None
    stale_reason: list[str] | None
    stale_since: datetime | None
    session_id: int | None
    sent_at: datetime | None
    from_user: str | None
    summary_note: str | None      # 보낸 사람의 교대 총평
    version_no_at_transfer: int | None
    item_note: str | None
    carry_depth: int | None


class BulkAckRequest(BaseModel):
    handover_ids: list[int] = Field(min_length=1, max_length=500)


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str | None
    link_type: str | None
    link_id: int | None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
