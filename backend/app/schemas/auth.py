from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.group import MyGroupOut


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserBrief(BaseModel):
    id: int
    username: str
    display_name: str
    role_code: str
    team: str | None = None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    role_code: str
    team: str | None
    must_change_password: bool
    last_login_at: datetime | None
    permissions: list[str]
    pending_ack_count: int = 0
    unread_notification_count: int = 0
    #: 내가 속한 열람 그룹(기본 그룹이 맨 앞). 글 쓸 때 공개 범위 선택지가 된다.
    groups: list[MyGroupOut] = []

    model_config = {"from_attributes": True}


class SessionInfo(BaseModel):
    id: int
    issued_at: datetime
    expires_at: datetime
    client_ip: str | None
    user_agent: str | None
    current: bool = False
