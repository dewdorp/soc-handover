"""감사 로그 · 설정 · 댓글 · 첨부 스키마 (Phase 8)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditSearch(BaseModel):
    """기간은 필수(최대 93일). ANALYST 는 user 조건과 상관없이 자기 행위만 본다."""
    start: datetime
    end: datetime
    user_id: int | None = None
    username: str | None = Field(default=None, max_length=64)
    actions: list[str] | None = Field(default=None, max_length=40)
    resource_type: str | None = Field(default=None, max_length=30)
    resource_id: str | None = Field(default=None, max_length=50)
    client_ip: str | None = Field(default=None, max_length=45)
    result: Literal["SUCCESS", "FAILURE"] | None = None
    order: Literal["desc", "asc"] = "desc"
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)


class AuditOut(BaseModel):
    id: int
    occurred_at: datetime
    user_id: int | None
    username: str | None
    role_code: str | None
    client_ip: str | None
    user_agent: str | None
    request_id: str | None
    action: str
    action_label: str
    resource_type: str | None
    resource_id: str | None
    before_value: Any = None
    after_value: Any = None
    result: str
    error_message: str | None
    detail: Any = None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    size: int


class SettingUpdate(BaseModel):
    value: Any


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)


class HandoverCommentOut(BaseModel):
    id: int
    handover_id: int
    body: str
    author_id: int | None
    author: str | None
    created_at: datetime
    is_edited: bool
    edited_at: datetime | None
    can_edit: bool
    can_delete: bool


class AttachmentOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    name: str
    size: int
    mime: str | None
    sha256: str | None
    scan_status: str
    uploaded_by: str | None
    created_at: datetime
    can_delete: bool
    #: 화면에서 바로 미리 볼 수 있는 그림인가(파일 내용으로 판단)
    is_image: bool = False
