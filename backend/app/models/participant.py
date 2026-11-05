"""업무에 걸린 사람들 — 누가 맡고, 누가 꼭 확인해야 하고, 누가 알고만 있으면 되는가.

왜 assignee_id 하나로는 모자란가
  침해사고 한 건에는 보통 셋이 섞인다. 실제로 손을 대는 사람(담당), 자기 몫은 없지만
  **확인은 반드시 해야** 하는 사람(교대 인수자 · 승인자), 알고만 있으면 되는 사람(참고).
  이 셋을 구분하지 않으면 '모두에게 보냈는데 아무도 확인하지 않은' 상태가 생기고,
  반대로 참고로 보낸 사람까지 확인 대기로 잡혀 미확인 숫자가 늘 빨갛게 남는다.

역할
  OWNER     대표 담당 — 한 건에 한 명. handovers.assignee_id 와 같은 사람이다.
  CO_OWNER  공동 담당 — 함께 손대는 사람. 확인 의무가 있다.
  REQUIRED  필수 인수자 — 손대지 않지만 **확인해야** 끝난다.
  FYI       참고 전파 — 보이고 알림도 가지만 확인 의무는 없다.

한 사람은 한 역할만 가진다(uq_handover_participant). 같은 사람이 '담당'이자 '참고'로
두 번 들어가면 확인 숫자가 두 번 세어진다 — 전파할 때 사람 id 로 합치는 이유다.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

ROLE_OWNER = "OWNER"
ROLE_CO_OWNER = "CO_OWNER"
ROLE_REQUIRED = "REQUIRED"
ROLE_FYI = "FYI"
PARTICIPANT_ROLES: tuple[str, ...] = (ROLE_OWNER, ROLE_CO_OWNER, ROLE_REQUIRED, ROLE_FYI)

#: 확인(ack) 의무가 있는 역할. 참고(FYI)는 빠진다.
MUST_ACK: frozenset[str] = frozenset({ROLE_OWNER, ROLE_CO_OWNER, ROLE_REQUIRED})

ROLE_LABEL: dict[str, str] = {
    ROLE_OWNER: "대표 담당",
    ROLE_CO_OWNER: "공동 담당",
    ROLE_REQUIRED: "필수 인수자",
    ROLE_FYI: "참고",
}

#: 역할이 겹칠 때 센 쪽. 전파하다 같은 사람이 두 역할로 들어오면 **강한 쪽**을 남긴다
#: (참고로 받던 사람이 담당으로 지정되면 담당이 이긴다).
ROLE_RANK: dict[str, int] = {ROLE_OWNER: 0, ROLE_CO_OWNER: 1, ROLE_REQUIRED: 2, ROLE_FYI: 3}


class HandoverParticipant(Base, TimestampMixin):
    __tablename__ = "handover_participants"
    __table_args__ = (
        UniqueConstraint("handover_id", "user_id", name="uq_handover_participant"),
        Index("ix_hp_user_role", "user_id", "role"),
        Index("ix_hp_handover_role", "handover_id", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id", ondelete="CASCADE"),
                                             nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    #: 왜 넣었는지(전파 사유 · 승인 요청 등). 전파로 들어온 사람은 그 묶음 이름이 적힌다.
    note: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    user = relationship("User", foreign_keys=[user_id], lazy="joined")
