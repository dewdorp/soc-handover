"""장비 비밀번호 보관 스키마.

**응답에는 비밀번호가 없다.** 값은 오직 RevealOut(= /reveal 응답) 으로만 나간다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Scope = Literal["SHARED", "PERSONAL"]


class CredentialOut(BaseModel):
    id: int
    scope: Scope
    company_id: int | None
    company: str | None
    device_name: str
    access_method: str | None
    username: str | None
    note: str | None
    owner_id: int
    owner: str | None
    rotated_at: datetime | None
    rotated_by: str | None
    current_version_no: int
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class CredentialCreate(BaseModel):
    scope: Scope = "SHARED"
    company_id: int | None = None
    device_name: str = Field(min_length=1, max_length=200)
    access_method: str | None = Field(default=None, max_length=2000)
    username: str | None = Field(default=None, max_length=200)
    secret: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class CredentialUpdate(BaseModel):
    scope: Scope | None = None
    company_id: int | None = None
    device_name: str | None = Field(default=None, min_length=1, max_length=200)
    access_method: str | None = Field(default=None, max_length=2000)
    username: str | None = Field(default=None, max_length=200)
    #: 주면 비밀번호를 바꾸고, 바꾸기 전 값은 이력에 남는다
    secret: str | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=500)


class RevealRequest(BaseModel):
    #: 본인 계정 비밀번호(자리를 비운 사이 남이 열어 보는 것을 막는다)
    password: str = Field(min_length=1, max_length=200)


class RevealOut(BaseModel):
    credential_id: int
    version_no: int
    secret: str
    device_name: str
    username: str | None


class CredentialVersionOut(BaseModel):
    version_no: int
    changed_fields: list[str]
    changed_by: str | None
    changed_at: datetime
    change_note: str | None
    device_name: str | None
    username: str | None
    #: 옛 비밀번호 값이 아직 남아 있는가(오래된 이력은 값을 지운다)
    has_secret: bool
