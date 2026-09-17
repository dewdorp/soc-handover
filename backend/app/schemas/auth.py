from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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

    model_config = {"from_attributes": True}


class SessionInfo(BaseModel):
    id: int
    issued_at: datetime
    expires_at: datetime
    client_ip: str | None
    user_agent: str | None
    current: bool = False
