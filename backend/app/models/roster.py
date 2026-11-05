"""근무표 — 4조 2교대의 '누가 언제 근무인가'.

왜 날짜마다 행을 만들지 않는가
  4조 2교대는 **16일 주기로 완전히 되풀이**된다('주주주주' + '야비비'×4). 그래서 조마다
  주기 안의 위치(phase_days)만 적어 두면 어느 날짜의 근무도 계산으로 나온다. 1년치를
  행으로 깔면 365×4행이 되고, 기준일 하나를 고치는 순간 전부 다시 만들어야 한다.

  달라지는 것(대근 · 맞교환 · 휴무)만 roster_overrides 에 **예외로** 적는다. 그래서
  '계획'과 '실제'를 늘 구분해서 볼 수 있고, 되돌리기도 그 행 하나를 취소하면 끝난다.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, ForeignKey, Index, SmallInteger, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TZDateTime

#: 16일 주기. D=주간, N=야간, '.'=비번(휴무).
#: 주간 4일 → (야간, 비번, 비번) 4회. 조를 4일씩 밀어 두면 매일 주간 1조 · 야간 1조가 된다.
PATTERN: str = "DDDD" + "N.." * 4
CYCLE_DAYS: int = len(PATTERN)

SHIFT_DAY = "DAY"
SHIFT_NIGHT = "NIGHT"
SHIFT_OFF = "OFF"

#: 예외의 종류
OVR_SUB = "SUB"        # 대근 — 한 사람이 빠지고 다른 사람이 들어온다
OVR_SWAP = "SWAP"      # 맞교환 — 두 사람이 서로 근무를 바꾼다(SUB 두 줄로 적는다)
OVR_OFF = "OFF"        # 결원 — 한 사람이 빠지고 대신 들어오는 사람이 없다
OVR_KINDS = (OVR_SUB, OVR_SWAP, OVR_OFF)


class RosterTeam(Base, TimestampMixin):
    __tablename__ = "roster_teams"
    __table_args__ = (Index("ix_roster_team_active", "is_active", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    #: 기준일(roster.epoch_date)에서 이 조가 주기의 몇 번째 날에 있는가. 4조면 0·4·8·12.
    phase_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    members = relationship("RosterMember", cascade="all, delete-orphan", lazy="selectin",
                           order_by="RosterMember.sort_order, RosterMember.id")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RosterTeam {self.code}>"


class RosterMember(Base, TimestampMixin):
    __tablename__ = "roster_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_roster_member"),
        Index("ix_roster_member_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("roster_teams.id", ondelete="CASCADE"),
                                         nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         nullable=False)
    is_leader: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    user = relationship("User", lazy="joined")


class RosterOverride(Base, TimestampMixin):
    """하루치 근무 하나에 대한 예외. 취소하면 지우지 않고 canceled_at 을 적는다(이력)."""

    __tablename__ = "roster_overrides"
    __table_args__ = (
        Index("ix_roster_ovr_date", "work_date", "shift_code"),
        Index("ix_roster_ovr_off", "off_user_id", "work_date"),
        Index("ix_roster_ovr_on", "on_user_id", "work_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: 야간은 **시작 날짜**로 적는다. 11/05 야간은 11/05 18:00 ~ 11/06 09:00 이다.
    shift_code: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)

    #: 빠지는 사람(결원 · 대근 · 맞교환 모두 있다)
    off_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: 들어오는 사람. 결원(OFF)이면 비어 있다.
    on_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    #: 맞교환의 반대쪽 행. 한쪽을 취소하면 다른 쪽도 함께 취소한다.
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("roster_overrides.id"))

    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    canceled_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    canceled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    off_user = relationship("User", foreign_keys=[off_user_id], lazy="joined")
    on_user = relationship("User", foreign_keys=[on_user_id], lazy="joined")
