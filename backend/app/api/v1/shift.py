"""교대 인수인계 라우터 (API.md §4). 규칙은 services/shift_service.py 에 있다.

구체적인 경로(/cockpit, /basket, /inbox)를 /{session_id} 보다 먼저 선언한다.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.shift import ShiftHandover
from app.models.user import User
from app.schemas.shift import (AddItemsRequest, BasketOut, BasketUpdate, BulkAckRequest,
                               CockpitOut, InboxItem, ItemNoteRequest, SendRequest,
                               SessionItemOut, SessionOut)
from app.services import shift_service as svc

router = APIRouter(tags=["shift-handovers"], dependencies=[Depends(require_password_changed)])
P = "/shift-handovers"


def _session_out(db: Session, session: ShiftHandover, *, with_items: bool = True) -> dict:
    views = svc.item_views(db, session) if with_items else []
    sender = db.get(User, session.from_user_id)
    receivers = [db.get(User, r.user_id) for r in session.recipients]
    return {
        "id": session.id, "status": session.status, "shift_date": session.shift_date,
        "shift_id": session.shift_id, "to_shift_id": session.to_shift_id,
        "from_user_id": session.from_user_id,
        "from_user": sender.display_name if sender else None,
        "to_user_ids": [r.user_id for r in session.recipients],
        "to_users": [u.display_name for u in receivers if u],
        "sent_at": session.sent_at, "closed_at": session.closed_at,
        "summary_note": session.summary_note,
        "item_count": session.item_count or len(session.items),
        "acked_count": svc.acked_count(views) if with_items else session.acked_count,
        "items": [SessionItemOut.model_validate(v) for v in views],
    }


@router.get(f"{P}/cockpit", response_model=CockpitOut)
def cockpit(shift_date: date | None = None, shift_id: int | None = None,
            area: str | None = Query(default=None, max_length=30),
            size: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db),
            actor: User = Depends(require("handover:read"))):
    """근무 중 신규 · 진행 중 · 확인 필요 · 다음 근무 예정 · 중요 · 지연 (FR-C-01).

    `area` 로 지금 보고 있는 영역을 알려 주면 그 영역의 목록만 만든다(나머지는 숫자만).
    """
    return svc.cockpit(db, actor, shift_date=shift_date, shift_id=shift_id, size=size, area=area)


# --------------------------------------------------------------------------- Basket

@router.get(f"{P}/basket", response_model=BasketOut)
def get_basket(db: Session = Depends(get_db), actor: User = Depends(require("shift:transfer"))):
    basket, added = svc.get_basket(db, actor)
    return {**_session_out(db, basket), "auto_added": added,
            "carry_candidates": len(svc.carry_candidates(db, actor))}


@router.get(f"{P}/basket/carry-forward-candidates", response_model=list[SessionItemOut])
def carry_candidates(db: Session = Depends(get_db),
                     actor: User = Depends(require("shift:transfer"))):
    """직전 교대에서 나에게 넘어온 것 중 아직 끝나지 않은 것."""
    previous = svc.last_received(db, actor.id)
    if previous is None:
        return []
    wanted = {h.id for _, h in svc.carry_candidates(db, actor)}
    return [SessionItemOut.model_validate(v) for v in svc.item_views(db, previous)
            if v["handover_id"] in wanted]


@router.post(f"{P}/basket/items")
def add_items(payload: AddItemsRequest, db: Session = Depends(get_db),
              actor: User = Depends(require("shift:transfer"))):
    return svc.add_items(db, actor, payload.handover_ids, payload.item_note)


@router.patch(f"{P}/basket/items/{{item_id}}", response_model=SessionItemOut)
def update_item(item_id: int, payload: ItemNoteRequest, db: Session = Depends(get_db),
                actor: User = Depends(require("shift:transfer"))):
    item = svc.update_item(db, actor, item_id, payload.item_note)
    basket = db.get(ShiftHandover, item.session_id)
    return next(SessionItemOut.model_validate(v) for v in svc.item_views(db, basket)
                if v["item_id"] == item_id)


@router.delete(f"{P}/basket/items/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(item_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("shift:transfer"))):
    svc.remove_item(db, actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(f"{P}/basket", response_model=BasketOut)
def update_basket(payload: BasketUpdate, db: Session = Depends(get_db),
                  actor: User = Depends(require("shift:transfer"))):
    basket = svc.update_basket(db, actor, payload.model_dump(exclude_unset=True))
    return _session_out(db, basket)


@router.post(f"{P}/basket/send", response_model=SessionOut)
def send(payload: SendRequest, db: Session = Depends(get_db),
         actor: User = Depends(require("shift:transfer")),
         ctx: RequestContext = Depends(get_context)):
    """항목마다 전달 시점 버전을 고정하고, 인수자 **각각에게** 확인(PENDING)을 만든다."""
    session = svc.send(db, actor, to_user_ids=payload.to_user_ids,
                       to_shift_id=payload.to_shift_id, summary_note=payload.summary_note,
                       ctx=ctx)
    return _session_out(db, session)


# --------------------------------------------------------------------------- 인수 확인함 / 이력

@router.get(f"{P}/inbox", response_model=list[InboxItem])
def inbox(db: Session = Depends(get_db), actor: User = Depends(require("ack:write"))):
    """내가 확인하거나 다시 확인해야 할 것(UI_STRUCTURE §5.1)."""
    return svc.inbox(db, actor)


@router.get(P, response_model=list[SessionOut])
def list_sessions(direction: str = Query(default="all", pattern="^(all|sent|received|team)$"),
                  date_from: date | None = Query(default=None, alias="from"),
                  date_to: date | None = Query(default=None, alias="to"),
                  db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    """인계 이력. team 은 팀 전체(관리자가 누락을 점검할 때)."""
    user_id = None if direction == "team" else actor.id
    rows = svc.list_sessions(db, user_id=user_id, direction=direction,
                             date_from=date_from, date_to=date_to)
    return [_session_out(db, s) for s in rows]


@router.get(f"{P}/{{session_id}}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db),
                _: User = Depends(require("handover:read"))):
    return _session_out(db, svc.session_or_404(db, session_id))


@router.post(f"{P}/{{session_id}}/close", response_model=SessionOut)
def close(session_id: int, db: Session = Depends(get_db),
          actor: User = Depends(require("shift:transfer"))):
    """전원 확인된 인계만 닫힌다."""
    return _session_out(db, svc.close(db, actor, session_id))


# --------------------------------------------------------------------------- 일괄 확인

@router.post("/acknowledgements/bulk")
def bulk_acknowledge(payload: BulkAckRequest, db: Session = Depends(get_db),
                     actor: User = Depends(require("ack:write")),
                     ctx: RequestContext = Depends(get_context)):
    """선택 항목 일괄 확인(FR-C-09). 각 건은 누르는 순간의 버전으로 기록된다."""
    return svc.bulk_acknowledge(db, actor, payload.handover_ids, ctx)
