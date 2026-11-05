"""인수인계 도메인. 시스템의 중심 Aggregate.

핵심 원칙
  · handovers      = 현재 상태(조회·검색·정렬 대상). 버전 테이블을 JOIN하지 않는다.
  · handover_versions = append-only 스냅샷. UPDATE/DELETE 금지.
  · acknowledgements  = "누가 어느 Version을 확인했는가" (§32)
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, ForeignKey, Index, Integer, SmallInteger,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IPType, JSONType, StrListType, TimestampMixin, TZDateTime

# 확인 상태
ACK_NONE = "NONE"
ACK_PENDING = "PENDING"
ACK_ACKED = "ACKED"
ACK_REACK = "REACK_REQUIRED"

# 버전 변경 유형
CHANGE_CREATE = "CREATE"
CHANGE_UPDATE = "UPDATE"
CHANGE_RESTORE = "RESTORE"
CHANGE_DELETE = "DELETE"
CHANGE_UNDELETE = "UNDELETE"
CHANGE_IMPORT = "IMPORT"

#: 버전 스냅샷에 담기는 업무 필드(이 목록이 diff/복원/재확인 판정의 기준이다)
VERSIONED_FIELDS = (
    "company_id", "title", "content", "remark", "status_code", "priority_code",
    "registered_date", "work_date", "completed_at", "sender_id", "sender_name_raw",
    "assignee_id", "assignee_name_raw", "checker_id", "checker_name_raw",
    "is_important", "is_pinned", "is_recurring", "tags", "visibility", "group_ids",
)


class Handover(Base, TimestampMixin):
    __tablename__ = "handovers"
    __table_args__ = (
        Index("ix_ho_list", "is_deleted", "registered_date", "id"),
        Index("ix_ho_company_date", "company_id", "registered_date"),
        Index("ix_ho_open", "status_code", "work_date"),
        Index("ix_ho_assignee", "assignee_id", "status_code", "work_date"),
        Index("ix_ho_sender", "sender_id", "registered_date"),
        Index("ix_ho_ack", "ack_state_cache"),
        Index("ix_ho_fingerprint", "fingerprint"),
        Index("ix_ho_import", "import_job_id"),
        Index("ix_ho_updated", "updated_at"),
        Index("ix_ho_request", "request_state", "registered_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str | None] = mapped_column(Text)

    status_code: Mapped[str] = mapped_column(ForeignKey("handover_statuses.code"),
                                             nullable=False, default="NEW")
    priority_code: Mapped[str] = mapped_column(ForeignKey("priorities.code"),
                                               nullable=False, default="NORMAL")

    registered_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sender_name_raw: Mapped[str | None] = mapped_column(String(100))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assignee_name_raw: Mapped[str | None] = mapped_column(String(100))
    checker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    checker_name_raw: Mapped[str | None] = mapped_column(String(100))

    is_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: 공개 범위 — GROUPS(handover_groups 에 적힌 그룹) / ALL(로그인한 모든 사람).
    #: 기본값은 GROUPS 다. '전체 공개'는 쓴 사람이 명시적으로 고를 때만 된다.
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="GROUPS")

    current_version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ack_state_cache: Mapped[str] = mapped_column(String(20), nullable=False, default=ACK_NONE)
    last_transferred_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    carry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # Excel 원본 추적(§47)
    source_file: Mapped[str | None] = mapped_column(String(255))
    source_sheet: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("excel_import_jobs.id"))
    fingerprint: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)

    # 분석 의뢰 흐름(§5) — NONE → REQUESTED(의뢰) → ACCEPTED(접수) → ANSWERED(회신).
    # 한 업무에 흐름이 하나뿐이고 목록에서 '의뢰 중'을 걸러야 해서 같은 행에 둔다.
    request_state: Mapped[str] = mapped_column(String(12), nullable=False, default="NONE")
    requested_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    answered_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    request_note: Mapped[str | None] = mapped_column(Text)
    answer_note: Mapped[str | None] = mapped_column(Text)

    #: 검색용 결합 텍스트(제목+내용+비고+관계사+인명+태그). PG에서는 tsvector 컬럼이 추가된다.
    search_text: Mapped[str | None] = mapped_column(Text)

    company = relationship("Company", lazy="joined")
    status = relationship("HandoverStatus", lazy="joined")
    priority = relationship("Priority", lazy="joined")
    assignee = relationship("User", foreign_keys=[assignee_id], lazy="joined")
    sender = relationship("User", foreign_keys=[sender_id], lazy="joined")
    checker = relationship("User", foreign_keys=[checker_id], lazy="joined")
    tag_links = relationship("HandoverTag", cascade="all, delete-orphan", lazy="selectin")
    group_links = relationship("HandoverGroup", cascade="all, delete-orphan", lazy="selectin")
    participants = relationship("HandoverParticipant", cascade="all, delete-orphan",
                                lazy="selectin")


class HandoverVersion(Base):
    """append-only 버전 스냅샷(§22~§25)."""
    __tablename__ = "handover_versions"
    __table_args__ = (
        UniqueConstraint("handover_id", "version_no", name="uq_hv_handover_version"),
        Index("ix_hv_handover", "handover_id", "version_no"),
        Index("ix_hv_changed_by", "changed_by", "changed_at"),
        Index("ix_hv_changed_at", "changed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 변경된 필드의 "변경 전" 값만 담는다(전체 이전 상태는 v(n-1).after_data 가 제공)
    before_data: Mapped[dict | None] = mapped_column(JSONType)
    #: 변경 후 전체 스냅샷 — 이 한 행만으로 해당 시점을 재현할 수 있다
    after_data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    changed_fields: Mapped[list] = mapped_column(StrListType, nullable=False, default=list)
    change_reason: Mapped[str | None] = mapped_column(Text)
    restored_from_version: Mapped[int | None] = mapped_column(Integer)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    client_ip: Mapped[str | None] = mapped_column(IPType)
    user_agent: Mapped[str | None] = mapped_column(String(400))


class HandoverAcknowledgement(Base, TimestampMixin):
    """확인 증적. confirmed=true 가 아니라 '어느 버전을 확인했는지'를 남긴다(§32)."""
    __tablename__ = "handover_acknowledgements"
    __table_args__ = (
        UniqueConstraint("handover_id", "user_id", name="uq_ack_handover_user"),
        Index("ix_ack_user_state", "user_id", "state"),
        Index("ix_ack_handover_state", "handover_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=ACK_PENDING)
    acked_version_no: Mapped[int | None] = mapped_column(Integer)
    acked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    required_by_session_id: Mapped[int | None] = mapped_column(ForeignKey("shift_handovers.id"))
    stale_since: Mapped[datetime | None] = mapped_column(TZDateTime)
    stale_reason: Mapped[list | None] = mapped_column(StrListType)
    note: Mapped[str | None] = mapped_column(Text)


class HandoverStar(Base):
    """개인 즐겨찾기(★). 전역 is_pinned 과 구분(ASSUMPTIONS B-07)."""
    __tablename__ = "handover_stars"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class HandoverTag(Base):
    __tablename__ = "handover_tags"

    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    tag = relationship("Tag", lazy="joined")


class HandoverComment(Base, TimestampMixin):
    """본문과 분리된 댓글(§65). 버전을 생성하지 않는다."""
    __tablename__ = "handover_comments"
    __table_args__ = (Index("ix_hc_handover", "handover_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
