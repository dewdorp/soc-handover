"""열람 그룹 — '누가 어느 업무 원문을 볼 수 있는가'.

왜 역할(Role)과 따로 두는가
  역할은 '무엇을 할 수 있는가'(등록·삭제·가져오기)이고, 그룹은 '무엇을 볼 수 있는가'다.
  관리자는 그룹을 만들고 사람을 넣을 수 있지만, 그 권한이 **다른 그룹 업무의 원문을
  보여 주는 근거가 되지는 않는다**. 그래서 열람 판정에는 역할을 쓰지 않는다
  (group_service.visible_clause 가 유일한 판정자다).

구성
  groups           관리자가 만드는 그룹. 이름은 현장 그대로(예: '관제1팀', 'CERT').
  user_groups      사람 ↔ 그룹. 한 사람이 여러 그룹에 속할 수 있고, 그중 하나가 기본 그룹이다.
  handover_groups  업무 ↔ 공개 그룹. 업무 하나를 여러 그룹에 공개할 수 있다.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

#: 이관 전 자료가 모이는 자리. '전체 공개'가 아니라 **하나의 그룹**이다(§3 미분류 처리).
GROUP_UNCLASSIFIED: str = "UNCLASSIFIED"

#: 업무 공개 범위
VIS_GROUPS: str = "GROUPS"   # handover_groups 에 적힌 그룹만
VIS_ALL: str = "ALL"         # 로그인한 모든 사람(명시적으로 고른 경우에만)
VISIBILITIES: tuple[str, ...] = (VIS_GROUPS, VIS_ALL)


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (Index("ix_groups_active", "is_active", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 예약 그룹(UNCLASSIFIED)만 코드를 가진다. 사람이 만든 그룹은 None.
    code: Mapped[str | None] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Group {self.name}>"


class UserGroup(Base, TimestampMixin):
    __tablename__ = "user_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group"),
        Index("ix_ug_user", "user_id"),
        Index("ix_ug_group", "group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"),
                                          nullable=False)
    #: 새 업무를 쓸 때 기본으로 고를 그룹. 사람마다 최대 하나.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    group: Mapped[Group] = relationship(lazy="joined")


class HandoverGroup(Base):
    __tablename__ = "handover_groups"
    __table_args__ = (
        UniqueConstraint("handover_id", "group_id", name="uq_handover_group"),
        Index("ix_hg_group", "group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id", ondelete="CASCADE"),
                                             nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"),
                                          nullable=False)
