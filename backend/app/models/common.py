"""첨부 · 저장된 보기 · 알림 · 감사로그 · 설정 · 검색 피드백."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, ForeignKey, Index, Integer, SmallInteger,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IPType, JSONType, TimestampMixin, TZDateTime


class Attachment(Base, TimestampMixin):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_att_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # HANDOVER/TASK
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(100), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(300), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_SCANNED")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SavedView(Base, TimestampMixin):
    """Filter 뿐 아니라 그리드 상태 전체를 저장한다(§15)."""
    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("scope", "owner_id", "target", "name", name="uq_view_name"),
        Index("ix_view_target", "target", "scope", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="PERSONAL")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target: Mapped[str] = mapped_column(String(20), nullable=False, default="HANDOVER")
    state: Mapped[dict] = mapped_column(JSONType, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_noti_user", "user_id", "is_read", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link_type: Mapped[str | None] = mapped_column(String(20))
    link_id: Mapped[int | None] = mapped_column(BigInteger)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    dedup_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class AuditLog(Base):
    """행위 증적(§60~§61). Version History(내용 변경)와 분리한다."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_time", "occurred_at"),
        Index("ix_audit_user", "user_id", "occurred_at"),
        Index("ix_audit_action", "action", "occurred_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_uuid: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    #: 사용자 레코드가 바뀌어도 증적이 남도록 이름/역할을 비정규화해 보존한다
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    role_code: Mapped[str | None] = mapped_column(String(20))
    client_ip: Mapped[str | None] = mapped_column(IPType)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(30))
    resource_id: Mapped[str | None] = mapped_column(String(50))
    before_value: Mapped[dict | None] = mapped_column(JSONType)
    after_value: Mapped[dict | None] = mapped_column(JSONType)
    result: Mapped[str] = mapped_column(String(10), nullable=False, default="SUCCESS")
    error_message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONType)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="json")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="general")
    description: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class SearchFeedback(Base):
    __tablename__ = "search_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="GRID")
    result_count: Mapped[int | None] = mapped_column(Integer)
    clicked_handover_id: Mapped[int | None] = mapped_column(BigInteger)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
