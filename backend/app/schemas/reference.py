from __future__ import annotations

from datetime import time

from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    id: int
    code: str | None
    name: str
    short_name: str | None
    color: str | None
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    short_name: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=7)
    sort_order: int = 100


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    short_name: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=7)
    sort_order: int | None = None
    is_active: bool | None = None


class StatusOut(BaseModel):
    code: str
    name: str
    category: str
    color: str | None
    icon: str | None
    sort_order: int
    is_active: bool
    is_system: bool

    model_config = {"from_attributes": True}


class StatusUpsert(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=30)
    category: str = Field(pattern=r"^(OPEN|WAITING|CLOSED)$")
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=30)
    sort_order: int = 100
    is_active: bool = True


class PriorityOut(BaseModel):
    code: str
    name: str
    level: int
    color: str | None
    icon: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class ShiftOut(BaseModel):
    id: int
    code: str
    name: str
    start_time: time
    end_time: time
    crosses_midnight: bool
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None
    usage_count: int

    model_config = {"from_attributes": True}
