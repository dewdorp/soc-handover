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
        Index("ix_sh_from_user", "from_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    to_shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SESSION_DRAFT)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    summary_note: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    items = relationship("ShiftHandoverItem", cascade="all, delete-orphan",
                         order_by="ShiftHandoverItem.display_order", lazy="selectin")
    #: 인수자. 한 번의 인계를 여러 명에게 넘길 수 있다(야간→주간 2인 교대 등).
    recipients = relationship("ShiftHandoverRecipient", cascade="all, delete-orphan",
                              order_by="ShiftHandoverRecipient.display_order,"
                                       "ShiftHandoverRecipient.id", lazy="selectin")

    @property
    def recipient_ids(self) -> list[int]:
        return [r.user_id for r in self.recipients]


class ShiftHandoverRecipient(Base, TimestampMixin):
    """이 인계를 받는 사람. 누가 받았는지의 유일한 근거다(§27).

    확인(HandoverAcknowledgement)은 사람마다 따로 만들어지므로, 여러 명에게 넘긴 인계는
    **모두가 확인해야** 확인된 것으로 본다 — 한 명만 봐도 된다면 인계 누락을 못 잡는다.
    """

    __tablename__ = "shift_handover_recipients"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_shr_session_user"),
        Index("ix_shr_user", "user_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shift_handovers.id", ondelete="CASCADE"),
                                            nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: 화면에 보이는 순서(고른 순서 그대로). 대표·부대표 같은 뜻은 없다.
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


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
