"""복수 담당 · 전파 · 분석 의뢰 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["OWNER", "CO_OWNER", "REQUIRED", "FYI"]


class ParticipantIn(BaseModel):
    user_id: int
    role: Role = "REQUIRED"


class ParticipantOut(BaseModel):
    user_id: int
    display_name: str
    username: str
    role: str
    role_label: str
    must_ack: bool
    note: str | None = None


class ParticipantsUpdate(BaseModel):
    """통째로 바꾼다. 대표 담당(OWNER)은 한 명뿐이다."""
    participants: list[ParticipantIn] = Field(default_factory=list, max_length=200)
    note: str | None = Field(default=None, max_length=300)


class ParticipantCounts(BaseModel):
    owner: int = 0
    co_owner: int = 0
    required: int = 0
    fyi: int = 0
    total: int = 0
    must_ack: int = 0


class ParticipantsOut(BaseModel):
    participants: list[ParticipantOut] = []
    counts: ParticipantCounts


class PropagateRequest(BaseModel):
    """그룹 단위 전파. 미리보기와 같은 몸체를 쓴다 — 보고 누른 것과 실제가 같아야 한다."""
    group_ids: list[int] = Field(min_length=1, max_length=50)
    role: Role = "FYI"
    exclude_user_ids: list[int] = Field(default_factory=list, max_length=500)
    note: str | None = Field(default=None, max_length=300)


class PropagateGroup(BaseModel):
    id: int
    name: str
    member_count: int


class OutsideScopeWarning(BaseModel):
    """그룹 제한 글을 그 그룹 밖으로 전파할 때의 경고(§3)."""
    scope_groups: list[str] = []
    outside_groups: list[str] = []
    message: str


class PropagatePreview(BaseModel):
    groups: list[PropagateGroup] = []
    role: str
    role_label: str
    add_count: int
    add_user_ids: list[int] = []
    excluded_count: int
    excluded_by_hand: list[str] = []
    excluded_already_stronger: list[str] = []
    after: ParticipantCounts
    visibility_note: str
    #: 그룹 제한을 그 그룹 밖으로 넓히는 전파일 때만 채워진다
    outside_scope: OutsideScopeWarning | None = None
    applied: bool = False
    participants: list[ParticipantOut] = []


# --------------------------------------------------------------------------- 분석 의뢰

class RequestIn(BaseModel):
    to_user_ids: list[int] = Field(min_length=1, max_length=50)
    note: str = Field(min_length=1, max_length=5000)


class AcceptIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class AnswerIn(BaseModel):
    note: str = Field(min_length=1, max_length=20000)


class RequestOut(BaseModel):
    state: str
    state_label: str
    requested_at: datetime | None = None
    requested_by: int | None = None
    accepted_at: datetime | None = None
    accepted_by: int | None = None
    answered_at: datetime | None = None
    answered_by: int | None = None
    request_note: str | None = None
    answer_note: str | None = None
    next_actions: list[str] = []
