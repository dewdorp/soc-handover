"""열람 그룹 요청/응답 스키마."""
from __future__ import annotations

from datetime import datetime

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


# --------------------------------------------------------------------------- 전체 공개 전환
class PublicMigrationItem(BaseModel):
    id: int
    title: str
    created_at: datetime | None = None
    is_important: bool = False
    company: str | None = None
    author: str | None = None


class PublicMigrationPreview(BaseModel):
    """바꾸기 전에 관리자가 확인하는 내용 — 건수 · 목록 · 경고."""
    eligible: int
    visible_after: int
    deleted_included: int
    reader_count: int
    confirm_phrase: str
    items: list[PublicMigrationItem] = []
    truncated: bool = False
    warnings: list[str] = []


class PublicMigrationApply(BaseModel):
    #: 화면에 보여 준 문구를 그대로 입력해야 한다. 버튼 한 번으로는 전환하지 않는다.
    confirm: str = Field(min_length=1, max_length=50)
    #: DB 백업을 받았다는 관리자의 확인.
    backup_confirmed: bool = False


class PublicMigrationResult(BaseModel):
    batch_id: str
    converted: int


class PublicMigrationBatch(BaseModel):
    batch_id: str
    count: int
    converted_at: datetime | None = None
    converted_by: int | None = None
    converted_by_name: str | None = None
    reverted: int = 0
    revertable: bool = True


class PublicMigrationRevertResult(BaseModel):
    batch_id: str
    restored: int
    skipped: int


# --------------------------------------------------------------------------- 저장 전 범위 점검
class ScopeCheckRequest(BaseModel):
    """'이 범위로 올리면 누가 못 보는가' — 저장 전에 묻는다."""
    visibility: str | None = Field(default=None, max_length=20)
    group_ids: list[int] = Field(default_factory=list, max_length=30)
    #: 담당자 · 확인자 · 공동 담당 · 전파 대상으로 넣으려는 사람들
    user_ids: list[int] = Field(default_factory=list, max_length=200)


class ScopeOutsider(BaseModel):
    """지정한 그룹에 속하지 않은 사람.

    소속 그룹 **이름은 담지 않는다** — 이 응답으로 '누가 어느 조인지'를 긁어 갈 수
    있으면 구성원 목록을 관리자에게만 보여 주는 통제가 무의미해진다.
    """
    user_id: int
    display_name: str
    #: 어느 그룹에든 속해 있는가(어느 그룹인지는 알려 주지 않는다)
    has_any_group: bool = False


class ScopeCheckResult(BaseModel):
    visibility: str
    group_names: list[str] = []
    public: bool = False
    #: 지정한 그룹에 속하지 않은 사람들. 비어 있으면 경고할 것이 없다.
    outsiders: list[ScopeOutsider] = []
