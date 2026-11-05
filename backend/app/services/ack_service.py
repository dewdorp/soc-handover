"""확인(Acknowledgement) 서비스 — §32, FR-C-05/06/09.

핵심 판단 두 가지를 여기서 고정한다.

1) ack 에 남기는 버전은 **확인 버튼을 누른 시점의 current_version_no** 다.
   전달 시점 버전을 남기면 "확인한 뒤에 내용이 바뀌었는가"를 판정할 수 없다.
   (전달 시점 버전은 shift_handover_items 에 별도로 보존한다.)

2) handovers.ack_state_cache 는 **집계값**이다. 목록 필터의 1차 축소에만 쓰고,
   "내 확인상태" 컬럼은 로그인 사용자 기준으로 따로 조회한다.
   둘을 섞으면 화면이 거짓말을 한다(ASSUMPTIONS B-03).
"""
from __future__ import annotations

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.context import RequestContext
from app.core.errors import Conflict
from app.core.time import now
from app.models.handover import (ACK_ACKED, ACK_NONE, ACK_PENDING, ACK_REACK,
                                 Handover, HandoverAcknowledgement, HandoverVersion)
from app.services import settings_service

#: 집계 우선순위 — 위험한 상태가 이긴다.
_CACHE_PRIORITY = (ACK_REACK, ACK_PENDING, ACK_ACKED)


def reack_fields(db: Session) -> list[str]:
    value = settings_service.get_value(db, "ack.reack_fields")
    return list(value or [])


def recompute_cache(db: Session, handover: Handover) -> str:
    """해당 인수인계의 ack 집계 상태를 다시 계산해 반영한다."""
    states = set(db.scalars(
        select(HandoverAcknowledgement.state)
        .where(HandoverAcknowledgement.handover_id == handover.id)
    ))
    new_state = ACK_NONE
    for candidate in _CACHE_PRIORITY:
        if candidate in states:
            new_state = candidate
            break
    handover.ack_state_cache = new_state
    return new_state


def invalidate_on_change(db: Session, handover: Handover, changed_fields: list[str],
                         actor_id: int | None = None) -> list[str]:
    """재확인 대상 필드가 바뀌면 기존 확인을 REACK_REQUIRED 로 되돌린다(FR-C-06).

    **고친 사람 본인의 확인은 되돌리지 않는다.** 본인이 방금 바꾼 내용을 '다시 확인하라'고
    하면 알림이 소음이 되고, 소음이 된 알림은 아무도 보지 않는다. 대신 본인의 확인을
    새 버전으로 올려 '확인 후 변경'으로 보이지 않게 한다.

    Returns: 재확인을 유발한 필드 목록(없으면 빈 목록).
    """
    triggers = [f for f in changed_fields if f in set(reack_fields(db))]
    if not triggers:
        return []

    acked = db.scalars(
        select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id == handover.id,
            HandoverAcknowledgement.state == ACK_ACKED,
        )
    ).all()
    stamp = now()
    own = [a for a in acked if actor_id is not None and a.user_id == actor_id]
    for ack in own:
        ack.acked_version_no = handover.current_version_no
        ack.acked_at = stamp
    acked = [a for a in acked if a not in own]
    for ack in acked:
        ack.state = ACK_REACK
        ack.stale_since = stamp
        ack.stale_reason = triggers
    if acked or own:
        db.flush()
    if acked:
        # 확인한 사람이 모르면 재확인 상태도 의미가 없다. 같은 건은 알림 하나로 갱신한다.
        from app.services import notification_service
        from app.services.handover_service import FIELD_NAMES
        changed = ", ".join(FIELD_NAMES.get(f, f) for f in triggers)
        for ack in acked:
            notification_service.notify(
                db, user_id=ack.user_id, type_=notification_service.T_REACK,
                title=f"확인한 인수인계 #{handover.id} 의 내용이 바뀌었습니다",
                body=f"{handover.title} — 변경: {changed}. 다시 확인해 주십시오.",
                link_type="HANDOVER", link_id=handover.id,
                dedup_key=f"reack:{handover.id}")
    recompute_cache(db, handover)
    return triggers


class StaleAck(Conflict):
    """화면에 띄워 둔 버전과 지금 버전이 다르다 — 읽지 않은 내용을 확인 처리하지 않는다."""

    code = "stale_ack"
    message = "확인하려는 사이에 내용이 바뀌었습니다. 바뀐 내용을 보고 다시 확인하십시오."


def changed_since(db: Session, handover: Handover, version_no: int) -> list[str]:
    """version_no 다음으로 실제로 바뀐 필드 이름들(화면에 '무엇이 바뀌었는지' 보여 주려고)."""
    rows = db.scalars(select(HandoverVersion.changed_fields).where(
        HandoverVersion.handover_id == handover.id,
        HandoverVersion.version_no > version_no)).all()
    seen: list[str] = []
    for fields in rows:
        for field in fields or []:
            if field not in seen:
                seen.append(field)
    return seen


def check_version(db: Session, handover: Handover, expected_version: int | None) -> None:
    """화면이 보여 준 버전과 지금 버전이 같은지 본다.

    expected_version 이 None 이면 검사하지 않는다(버전 개념이 없는 내부 호출 전용).
    경합은 호출하는 쪽이 handover 를 **잠근 채로**(get_or_404(..., lock=True)) 넘겨 막는다 —
    그래야 '읽는 사이에 저장'이 끼어들지 못한다.
    """
    if expected_version is None or expected_version == handover.current_version_no:
        return
    raise StaleAck(detail={
        "handover_id": handover.id,
        "shown_version_no": expected_version,
        "current_version_no": handover.current_version_no,
        "changed_fields": changed_since(db, handover, expected_version),
    })


def acknowledge(db: Session, handover: Handover, user, *, expected_version: int | None = None,
                note: str | None = None,
                ctx: RequestContext | None = None) -> HandoverAcknowledgement:
    """현재 버전을 확인 처리한다. 같은 사용자가 여러 번 눌러도 행은 하나다.

    expected_version 은 **화면이 보여 준 버전**이다. 그 사이에 내용이 바뀌었으면 확인하지 않고
    StaleAck 을 던진다 — 읽지 않은 버전을 '확인함'으로 남기면 인계 증적이 거짓이 된다.
    """
    check_version(db, handover, expected_version)
    ack = db.scalar(
        select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id == handover.id,
            HandoverAcknowledgement.user_id == user.id,
        )
    )
    if ack is None:
        ack = HandoverAcknowledgement(handover_id=handover.id, user_id=user.id)
        db.add(ack)

    previous_state = ack.state
    ack.state = ACK_ACKED
    ack.acked_version_no = handover.current_version_no  # 확인 "시점"의 버전
    ack.acked_at = now()
    ack.stale_since = None
    ack.stale_reason = None
    if note is not None:
        ack.note = note
    db.flush()

    recompute_cache(db, handover)
    record(db, action=actions.HANDOVER_ACKNOWLEDGE, ctx=ctx, user=user,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"state": previous_state},
           after={"state": ACK_ACKED, "acked_version_no": ack.acked_version_no})
    return ack


def mark_pending(db: Session, handover: Handover, user_id: int,
                 *, session_id: int | None = None) -> HandoverAcknowledgement:
    """전달 대상자에게 미확인(PENDING) 을 생성한다. 이미 확인했으면 건드리지 않는다."""
    ack = db.scalar(
        select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id == handover.id,
            HandoverAcknowledgement.user_id == user_id,
        )
    )
    if ack is None:
        ack = HandoverAcknowledgement(handover_id=handover.id, user_id=user_id,
                                      state=ACK_PENDING)
        db.add(ack)
    elif ack.state == ACK_ACKED and ack.acked_version_no != handover.current_version_no:
        ack.state = ACK_REACK
        ack.stale_since = now()
    if session_id is not None:
        ack.required_by_session_id = session_id
    db.flush()
    recompute_cache(db, handover)
    return ack


def my_state(db: Session, handover_id: int, user_id: int) -> HandoverAcknowledgement | None:
    return db.scalar(
        select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id == handover_id,
            HandoverAcknowledgement.user_id == user_id,
        )
    )


def list_for_handover(db: Session, handover_id: int) -> list[HandoverAcknowledgement]:
    return list(db.scalars(
        select(HandoverAcknowledgement)
        .where(HandoverAcknowledgement.handover_id == handover_id)
        .order_by(HandoverAcknowledgement.id)
    ))


def pending_count(db: Session, user_id: int) -> int:
    """대시보드 배너용 — 내가 확인/재확인해야 할 건수(FR-C-04)."""
    from sqlalchemy import func

    return db.scalar(
        select(func.count())
        .select_from(HandoverAcknowledgement)
        .join(Handover, Handover.id == HandoverAcknowledgement.handover_id)
        .where(
            HandoverAcknowledgement.user_id == user_id,
            HandoverAcknowledgement.state.in_((ACK_PENDING, ACK_REACK)),
            Handover.is_deleted == false(),
        )
    ) or 0
