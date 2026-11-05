"""분석 의뢰 흐름 — 의뢰 → 접수 → 회신.

왜 상태를 따로 두는가
  관제가 CERT 에 "이것 좀 봐 달라"고 넘기는 일은 인수인계와 모양이 다르다. 인계는 '다음
  근무자에게 넘김'이고, 의뢰는 '다른 조직에 맡기고 **답을 기다림**'이다. 상태 코드
  (진행중 · 완료)로는 "맡겼는데 아직 접수도 안 됐다"를 표현할 수 없다.

  NONE → REQUESTED(의뢰함) → ACCEPTED(접수함) → ANSWERED(회신함)

  · 의뢰하면 받는 쪽이 **필수 인수자**로 걸린다 — 접수 여부를 추적할 사람이 있어야 한다.
  · 접수는 받는 쪽이 누른다. "언제 접수했는가"가 응답 시간을 재는 기준이 된다.
  · 회신은 내용을 남겨야 한다. 내용 없는 '회신함'은 증적이 아니다.
  · 되돌리기는 없다. 잘못 눌렀으면 다시 의뢰한다(상태 이력이 지워지면 따질 근거가 사라진다).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.audit import actions
from app.core.context import RequestContext
from app.core.errors import Conflict, ValidationFailed
from app.core.time import now
from app.models.handover import Handover
from app.models.participant import ROLE_REQUIRED
from app.models.user import User
from app.services.audit_service import record

STATE_NONE = "NONE"
STATE_REQUESTED = "REQUESTED"
STATE_ACCEPTED = "ACCEPTED"
STATE_ANSWERED = "ANSWERED"
STATES: tuple[str, ...] = (STATE_NONE, STATE_REQUESTED, STATE_ACCEPTED, STATE_ANSWERED)

STATE_LABEL: dict[str, str] = {
    STATE_NONE: "의뢰 없음",
    STATE_REQUESTED: "의뢰함",
    STATE_ACCEPTED: "접수함",
    STATE_ANSWERED: "회신함",
}

#: 어느 상태에서 어느 상태로 갈 수 있는가. 건너뛰기는 허용한다(접수 없이 바로 회신하는
#: 경우가 실제로 있다 — 간단한 건은 보자마자 답한다). 되돌리기는 허용하지 않는다.
ALLOWED: dict[str, tuple[str, ...]] = {
    STATE_NONE: (STATE_REQUESTED,),
    STATE_REQUESTED: (STATE_ACCEPTED, STATE_ANSWERED, STATE_REQUESTED),
    STATE_ACCEPTED: (STATE_ANSWERED,),
    STATE_ANSWERED: (STATE_REQUESTED,),      # 추가 질문 — 같은 건으로 다시 의뢰한다
}


def describe(handover: Handover) -> dict[str, Any]:
    return {
        "state": handover.request_state,
        "state_label": STATE_LABEL.get(handover.request_state, handover.request_state),
        "requested_at": handover.requested_at,
        "requested_by": handover.requested_by,
        "accepted_at": handover.accepted_at,
        "accepted_by": handover.accepted_by,
        "answered_at": handover.answered_at,
        "answered_by": handover.answered_by,
        "request_note": handover.request_note,
        "answer_note": handover.answer_note,
        "next_actions": list(ALLOWED.get(handover.request_state, ())),
    }


def _check(handover: Handover, target: str) -> None:
    current = handover.request_state or STATE_NONE
    if target not in ALLOWED.get(current, ()):
        raise Conflict(
            f"'{STATE_LABEL.get(current, current)}' 에서 "
            f"'{STATE_LABEL.get(target, target)}' 로는 바꿀 수 없습니다.",
            detail={"current": current, "target": target,
                    "allowed": list(ALLOWED.get(current, ()))})


def request(db: Session, handover: Handover, *, to_user_ids: list[int], note: str,
            actor: User, ctx: RequestContext | None = None) -> dict[str, Any]:
    """분석을 의뢰한다. 받는 사람은 **필수 인수자**로 걸린다(접수를 추적할 사람)."""
    from app.services import participant_service

    clean = (note or "").strip()
    if not clean:
        raise ValidationFailed("무엇을 봐 달라는 것인지 적으십시오.", detail={"field": "note"})
    if not to_user_ids:
        raise ValidationFailed("의뢰받을 사람을 고르십시오.", detail={"field": "to_user_ids"})
    _check(handover, STATE_REQUESTED)

    before = describe(handover)
    handover.request_state = STATE_REQUESTED
    handover.requested_at = now()
    handover.requested_by = actor.id
    handover.request_note = clean
    # 다시 의뢰하는 경우 앞선 접수·회신 기록은 지우지 않는다 — 이력이다.
    db.flush()

    participant_service.set_participants(
        db, handover, [{"user_id": uid, "role": ROLE_REQUIRED} for uid in to_user_ids],
        actor=actor, ctx=ctx, note=f"분석 의뢰: {clean[:80]}", replace=False)

    record(db, action=actions.HANDOVER_REQUEST, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"state": before["state"]},
           after={"state": STATE_REQUESTED, "to_user_ids": sorted(set(to_user_ids)),
                  "note": clean[:500]})
    _notify(db, handover, to_user_ids, actor,
            title=f"분석 의뢰: {handover.title}", body=clean[:200])
    return describe(handover)


def accept(db: Session, handover: Handover, *, note: str | None, actor: User,
           ctx: RequestContext | None = None) -> dict[str, Any]:
    """받는 쪽이 '맡았다'고 누른다. 여기서부터 응답 시간이 재어진다."""
    _check(handover, STATE_ACCEPTED)
    handover.request_state = STATE_ACCEPTED
    handover.accepted_at = now()
    handover.accepted_by = actor.id
    db.flush()
    record(db, action=actions.HANDOVER_REQUEST, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"state": STATE_REQUESTED},
           after={"state": STATE_ACCEPTED, "note": (note or "")[:500]})
    if handover.requested_by:
        _notify(db, handover, [handover.requested_by], actor,
                title=f"의뢰 접수: {handover.title}",
                body=f"{actor.display_name} 님이 접수했습니다.")
    return describe(handover)


def answer(db: Session, handover: Handover, *, note: str, actor: User,
           ctx: RequestContext | None = None) -> dict[str, Any]:
    """회신한다. **내용이 없으면 받지 않는다** — 내용 없는 '회신함'은 증적이 아니다."""
    clean = (note or "").strip()
    if not clean:
        raise ValidationFailed("회신 내용을 적으십시오.", detail={"field": "note"})
    _check(handover, STATE_ANSWERED)

    handover.request_state = STATE_ANSWERED
    handover.answered_at = now()
    handover.answered_by = actor.id
    handover.answer_note = clean
    db.flush()
    record(db, action=actions.HANDOVER_REQUEST, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"state": STATE_ACCEPTED},
           after={"state": STATE_ANSWERED, "note": clean[:500]})
    if handover.requested_by:
        _notify(db, handover, [handover.requested_by], actor,
                title=f"의뢰 회신: {handover.title}", body=clean[:200])
    return describe(handover)


def _notify(db: Session, handover: Handover, user_ids: list[int], actor: User,
            *, title: str, body: str) -> None:
    from app.services import notification_service as ns

    for uid in {u for u in user_ids if u and u != actor.id}:
        ns.notify_once(db, user_id=uid, type_=ns.T_ASSIGNED, title=title, body=body,
                       link_type="HANDOVER", link_id=handover.id,
                       dedup_key=(f"request:{handover.id}:{uid}:{handover.request_state}:"
                                  f"{(handover.requested_at or handover.created_at).isoformat()}"))
