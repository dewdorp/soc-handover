"""인수인계 요청/응답 스키마.

수정 요청에는 expected_version 이 **필수**다(§26). 이 값을 빼먹으면 422 로 막히므로
"몰라서 덮어썼다"가 구조적으로 불가능하다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.auth import UserBrief
from app.schemas.reference import CompanyOut, PriorityOut, StatusOut

#: 낙관적 잠금/사유는 업무 필드가 아니므로 변경분에서 제외한다.
_META_FIELDS = ("expected_version", "change_reason")


# --------------------------------------------------------------------------- 입력

class HandoverCreate(BaseModel):
    company_id: int
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=100_000)
    remark: str | None = Field(default=None, max_length=100_000)
    status_code: str = Field(default="NEW", max_length=20)
    priority_code: str = Field(default="NORMAL", max_length=20)
    registered_date: date | None = None
    work_date: date | None = None
    completed_at: datetime | None = None
    sender_id: int | None = None
    sender_name_raw: str | None = Field(default=None, max_length=100)
    assignee_id: int | None = None
    assignee_name_raw: str | None = Field(default=None, max_length=100)
    checker_id: int | None = None
    checker_name_raw: str | None = Field(default=None, max_length=100)
    is_important: bool = False
    is_recurring: bool = False
    tags: list[str] | None = Field(default=None, max_length=30)


class HandoverUpdate(BaseModel):
    """부분 수정. 보낸 필드만 반영한다(exclude_unset)."""
    expected_version: int = Field(ge=1)
    change_reason: str | None = Field(default=None, max_length=500)

    company_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=100_000)
    remark: str | None = Field(default=None, max_length=100_000)
    status_code: str | None = Field(default=None, max_length=20)
    priority_code: str | None = Field(default=None, max_length=20)
    registered_date: date | None = None
    work_date: date | None = None
    completed_at: datetime | None = None
    sender_id: int | None = None
    sender_name_raw: str | None = Field(default=None, max_length=100)
    assignee_id: int | None = None
    assignee_name_raw: str | None = Field(default=None, max_length=100)
    checker_id: int | None = None
    checker_name_raw: str | None = Field(default=None, max_length=100)
    is_important: bool | None = None
    is_pinned: bool | None = None
    is_recurring: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=30)

    def changes(self) -> dict[str, Any]:
        data = self.model_dump(exclude_unset=True)
        for key in _META_FIELDS:
            data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _require_something(self):
        if not self.changes():
            raise ValueError("변경할 필드를 하나 이상 지정하십시오.")
        return self


class DeleteRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RestoreRequest(BaseModel):
    expected_version: int = Field(ge=1)
    change_reason: str = Field(min_length=1, max_length=500)


class AcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class PinRequest(BaseModel):
    pinned: bool = True


# --------------------------------------------------------------------------- 출력

class AckOut(BaseModel):
    user_id: int
    user: UserBrief | None = None
    state: str
    acked_version_no: int | None
    acked_at: datetime | None
    stale_since: datetime | None
    stale_reason: list[str] | None
    note: str | None

    model_config = {"from_attributes": True}


class HandoverListItem(BaseModel):
    """그리드 한 행. 버전 테이블을 JOIN 하지 않는다(성능)."""
    id: int
    company: CompanyOut | None
    title: str
    status: StatusOut | None
    priority: PriorityOut | None
    registered_date: date
    work_date: date | None
    completed_at: datetime | None
    sender: UserBrief | None
    sender_name_raw: str | None
    assignee: UserBrief | None
    assignee_name_raw: str | None
    checker: UserBrief | None
    checker_name_raw: str | None
    is_important: bool
    is_pinned: bool
    is_recurring: bool
    current_version_no: int
    #: 전체 집계(필터 1차 축소용). "내 확인상태"는 my_ack_state 를 봐야 한다.
    ack_state_cache: str
    my_ack_state: str | None = None
    is_starred: bool = False
    tags: list[str] = []
    carry_count: int
    updated_at: datetime
    is_deleted: bool

    model_config = {"from_attributes": True}


class HandoverDetail(HandoverListItem):
    content: str
    remark: str | None
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    deleted_at: datetime | None
    deleted_by: int | None
    delete_reason: str | None
    source_file: str | None
    source_sheet: str | None
    source_row: int | None
    acknowledgements: list[AckOut] = []


class VersionSummary(BaseModel):
    version_no: int
    change_type: str
    changed_fields: list[str]
    change_reason: str | None
    restored_from_version: int | None
    changed_by: int | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class VersionDetail(VersionSummary):
    before_data: dict[str, Any] | None
    after_data: dict[str, Any]
    client_ip: str | None
    user_agent: str | None


class DiffField(BaseModel):
    field: str
    before: Any = None
    after: Any = None
    ops: list[dict[str, str]] | None = None


class DiffOut(BaseModel):
    handover_id: int
    from_version: int
    to_version: int
    changed_fields: list[str]
    fields: list[DiffField]


class TimelineEvent(BaseModel):
    kind: str
    at: datetime
    actor_id: int | None
    title: str
    detail: dict[str, Any]


class AsOfOut(BaseModel):
    """지정 시각의 상태 재현 결과(P-07)."""
    handover_id: int
    as_of: datetime
    version_no: int
    change_type: str
    changed_at: datetime
    data: dict[str, Any]
