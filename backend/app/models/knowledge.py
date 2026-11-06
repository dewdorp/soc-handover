"""SOC 운영 지식: 작업 절차, 점검 체크리스트, 참고 문서."""
from __future__ import annotations

from datetime import date
from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class KnowledgeArticle(Base, TimestampMixin):
    __tablename__ = "knowledge_articles"
    __table_args__ = (
        Index("ix_knowledge_recent", "is_deleted", "updated_at"),
        Index("ix_knowledge_category", "category", "is_deleted"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="운영 절차")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_due: Mapped[date | None] = mapped_column(Date)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    group_links: Mapped[list["KnowledgeGroup"]] = relationship(
        "KnowledgeGroup", cascade="all, delete-orphan", lazy="selectin"
    )


class KnowledgeGroup(Base):
    __tablename__ = "knowledge_groups"
    __table_args__ = (
        UniqueConstraint("article_id", "group_id", name="uq_knowledge_group"),
        Index("ix_knowledge_group_gid", "group_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
