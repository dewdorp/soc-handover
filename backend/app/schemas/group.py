"""열람 그룹 요청/응답 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


class GroupOut(BaseModel):
    id: int
    code: str | None
    name: str
    description: str | None
    is_active: bool
    sort_order: int
    member_count: int = 0
    handover_count: int = 0


class MyGroupOut(BaseModel):
    """내가 속한 그룹 — 글 쓸 때 공개 범위 고르는 데 쓴다."""
    id: int
    name: str
    code: str | None = None
    is_default: bool = False


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0, le=9999)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = None


class GroupMemberOut(BaseModel):
    user_id: int
    username: str
    display_name: str
    role_code: str
    is_active: bool
    is_default: bool = False


class MembershipUpdate(BaseModel):
    """한 사람의 소속을 통째로 바꾼다. 비우면 모든 그룹에서 뺀다."""
    group_ids: list[int] = Field(default_factory=list, max_length=50)
    default_group_id: int | None = None


class MoveUnclassified(BaseModel):
    to_group_id: int
    #: 관계사별로 나눠 옮길 때. 비우면 전부.
    company_id: int | None = None
    #: 한 번에 옮길 최대 건수(큰 DB 에서 나눠 돌리기 위한 안전장치).
    limit: int | None = Field(default=None, ge=1, le=100_000)


class UnclassifiedCompany(BaseModel):
    company_id: int
    company_name: str
    count: int


class UnclassifiedSummary(BaseModel):
    group_id: int
    group_name: str
    total: int
    by_company: list[UnclassifiedCompany] = []


class MoveResult(BaseModel):
    moved: int
    remaining: int
    to_group_id: int
