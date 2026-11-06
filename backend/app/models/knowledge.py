"""SOC 운영 지식: 작업 절차, 점검 체크리스트, 참고 문서."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
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
    tag_links: Mapped[list["KnowledgeTag"]] = relationship(
        "KnowledgeTag", cascade="all, delete-orphan", lazy="selectin"
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


class KnowledgeTag(Base):
    """문서 태그. 검색·분류에 쓴다(한 문서에 여러 개)."""

    __tablename__ = "knowledge_tags"
    __table_args__ = (
        UniqueConstraint("article_id", "tag", name="uq_knowledge_tag"),
        Index("ix_knowledge_tag", "tag"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(40), nullable=False)


class KnowledgeRevision(Base):
    """개정 이력. 판올림마다 한 줄 — 이 줄이 있어야 버전 비교와 복원이 된다.

    본문을 그대로 담는다. 운영 절차 문서는 '그때 무엇이라고 적혀 있었는지'가
    사고 조사에서 근거가 되므로, 지면을 아끼려고 요약만 남기지 않는다.
    """

    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("article_id", "version_no", name="uq_knowledge_revision"),
        Index("ix_knowledge_revision_article", "article_id", "version_no"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    tags: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: 무엇을 왜 바꿨는지. 비워 둘 수 있지만 적어 두면 뒤에 보는 사람이 덜 묻는다.
    change_note: Mapped[str | None] = mapped_column(String(300))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeHandoverLink(Base):
    """문서 ↔ 인수인계 연결.

    연결 자체는 열람 권한을 넓히지 않는다. 읽는 사람이 볼 수 없는 인수인계는
    목록에서 아예 빠진다(knowledge_service.links_of 가 판정한다).
    """

    __tablename__ = "knowledge_handover_links"
    __table_args__ = (
        UniqueConstraint("article_id", "handover_id", name="uq_knowledge_handover"),
        Index("ix_knowledge_link_handover", "handover_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False
    )
    handover_id: Mapped[int] = mapped_column(
        ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
