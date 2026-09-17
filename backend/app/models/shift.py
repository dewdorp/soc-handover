"""교대 인수인계 세션/항목(§27~§34)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, ForeignKey, Index, Integer, SmallInteger,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TZDateTime

SESSION_DRAFT = "DRAFT"
SESSION_SENT = "SENT"
SESSION_CLOSED = "CLOSED"


class ShiftHandover(Base, TimestampMixin):
    __tablename__ = "shift_handovers"
    __table_args__ = (
        Index("ix_sh_date", "shift_date", "shift_id"),
        Index("ix_sh_to_user", "to_user_id", "status"),
        Index("ix_sh_from_user", "from_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    to_shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SESSION_DRAFT)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    summary_note: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    items = relationship("ShiftHandoverItem", cascade="all, delete-orphan",
                         order_by="ShiftHandoverItem.display_order", lazy="selectin")


class ShiftHandoverItem(Base, TimestampMixin):
    __tablename__ = "shift_handover_items"
    __table_args__ = (
        UniqueConstraint("session_id", "handover_id", name="uq_shi_session_handover"),
        Index("ix_shi_handover", "handover_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shift_handovers.id", ondelete="CASCADE"),
                                            nullable=False)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"), nullable=False)
    #: 전달 시점의 버전. 확인 시점 버전(ack)과 구분해서 보존한다(ASSUMPTIONS B-03).
    version_no_at_transfer: Mapped[int | None] = mapped_column(Integer)
    item_note: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    carried_from_item_id: Mapped[int | None] = mapped_column(Integer)
    is_carry_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
