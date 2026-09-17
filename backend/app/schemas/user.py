from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    role_code: str = Field(default="ANALYST", max_length=20)
    email: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    must_change_password: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    role_code: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    role_code: str
    team: str | None
    phone: str | None
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PasswordResetOut(BaseModel):
    username: str
    temporary_password: str
    message: str = "임시 비밀번호는 이 화면에서만 확인할 수 있습니다. 최초 로그인 시 변경이 필요합니다."
