"""교대 인수인계 — Cockpit · Basket · 전달 · Carry Forward (ARCHITECTURE §4, FR-C).

핵심 원칙
  · 인계는 **사람의 명시적 행위**다. 미완료를 자동으로 SENT 하지 않는다(B-06).
    직전 교대에서 받은 미완료는 Basket 에 자동으로 '담기만' 하고, 빼는 것은 사람이 한다.
  · 전달 시점의 버전을 항목마다 고정한다(version_no_at_transfer). 확인 시점의 버전은
    ack 에 따로 남는다(B-03). 둘을 비교하면 '전달 뒤에 바뀌었는지'를 알 수 있다.
  · Carry Forward 는 복제가 아니다. 같은 handover_id 를 계속 가리키고, 이전 항목을
    carried_from_item_id 로 이어서 'N교대째 인계 중'을 계산한다.
  · Cockpit 의 여섯 영역은 인수인계 목록과 **같은 필터 DSL** 로 센다. 숫자와 목록이
    어긋나지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.time import KST, ShiftWindow, now, resolve_shift
from app.models.handover import (ACK_ACKED, Handover, HandoverAcknowledgement)
from app.models.reference import HandoverStatus, Shift
from app.models.shift import (SESSION_CLOSED, SESSION_DRAFT, SESSION_SENT, ShiftHandover,
                              ShiftHandoverItem)
from app.models.user import User
from app.search.dsl import Filter, SearchRequest, Sort
from app.services import ack_service, notification_service, search_service, settings_service

MAX_CHAIN = 100


# --------------------------------------------------------------------------- 교대 시각

def _defs(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(Shift).where(Shift.is_active.is_(True))
                      .order_by(Shift.sort_order)).all()
    return [{"code": s.code, "start_time": s.start_time.strftime("%H:%M"),
             "end_time": s.end_time.strftime("%H:%M"), "crosses_midnight": s.crosses_midnight}
            for s in rows]


def _shift_by_code(db: Session, code: str) -> Shift | None:
    return db.scalar(select(Shift).where(Shift.code == code))


def current_window(db: Session, at: datetime | None = None) -> ShiftWindow:
    window = resolve_shift(_defs(db), at or now())
    if window is None:
        raise ValidationFailed("현재 시각에 해당하는 교대가 없습니다. 교대 정의를 확인하십시오.")
    return window


def window_for(db: Session, shift_date: date, shift_id: int) -> ShiftWindow:
    """지난 교대의 Cockpit 을 볼 때 — 그 날짜의 그 교대 시간대."""
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise NotFound("교대를 찾을 수 없습니다.")
    start = datetime.combine(shift_date, shift.start_time, tzinfo=KST)
    end_day = shift_date + timedelta(days=1) if (shift.crosses_midnight
                                                 or shift.end_time <= shift.start_time) else shift_date
    end = datetime.combine(end_day, shift.end_time, tzinfo=KST)
    return ShiftWindow(shift.code, shift_date, start, end)


def next_window(db: Session, window: ShiftWindow) -> ShiftWindow:
    """다음 교대 = 이번 교대가 끝나는 순간에 시작하는 교대."""
    following = resolve_shift(_defs(db), window.end_at + timedelta(seconds=1))
    return following or window


def describe(db: Session, window: ShiftWindow) -> dict[str, Any]:
    shift = _shift_by_code(db, window.code)
    return {"shift_id": shift.id if shift else None, "code": window.code,
            "name": shift.name if shift else window.code,
            "shift_date": window.shift_date.isoformat(),
            "start_at": window.start_at.isoformat(), "end_at": window.end_at.isoformat()}


def _minutes(t) -> int:
    return t.hour * 60 + t.minute


def validate_coverage(rows: list[tuple[str, Any, Any]]) -> None:
    """활성 교대가 하루 24시간을 **빈틈도 겹침도 없이** 덮는지 검사한다.

    빈틈이 있으면 그 시각에는 '현재 교대'가 없어 Cockpit·인계가 멈추고, 겹치면 같은
    시각이 두 교대에 속해 누가 인계받는지 모호해진다. 저장 전에 막는다.
    rows: (이름, 시작 time, 종료 time) — 종료 <= 시작이면 자정을 넘는 교대.
    """
    if not rows:
        raise ValidationFailed("활성 교대가 하나도 없습니다. 최소 하나는 있어야 합니다.")
    cover = [[] for _ in range(24 * 60)]
    for name, start, end in rows:
        s, e = _minutes(start), _minutes(end)
        span = list(range(s, e)) if e > s else list(range(s, 1440)) + list(range(0, e))
        for m in span:
            cover[m].append(name)
    fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
    gap = next((m for m, who in enumerate(cover) if not who), None)
    if gap is not None:
        raise ValidationFailed(f"{fmt(gap)} 에 해당하는 교대가 없습니다. 교대가 하루 24시간을 빈틈없이 덮어야 합니다.",
                               detail={"gap_at": fmt(gap)})
    overlap = next((m for m, who in enumerate(cover) if len(who) > 1), None)
    if overlap is not None:
        raise ValidationFailed(f"{fmt(overlap)} 이 {', '.join(cover[overlap])} 에 겹칩니다.",
                               detail={"overlap_at": fmt(overlap), "shifts": cover[overlap]})


# --------------------------------------------------------------------------- Cockpit

AREAS: list[tuple[str, str]] = [
    ("new_in_shift", "근무 중 신규"),
    ("in_progress", "진행 중"),
    ("need_ack", "확인 필요"),
    ("planned_next", "다음 근무 예정"),
    ("important", "중요"),
    ("overdue", "지연"),
]


def area_request(key: str, window: ShiftWindow, following: ShiftWindow,
                 size: int = 50) -> SearchRequest:
    """영역 정의 = 목록 DSL. 화면에서 '목록으로 보기'를 누르면 같은 조건이 그대로 간다."""
    sort = [Sort(field="registered_date", dir="desc")]
    if key == "new_in_shift":
        return SearchRequest(filters=[Filter(field="created_at", op="between", value=[
            window.start_at.isoformat(), window.end_at.isoformat()])], sort=sort, size=size)
    if key == "in_progress":
        return SearchRequest(quick=["IN_PROGRESS"], sort=sort, size=size)
    if key == "need_ack":
        return SearchRequest(quick=["NEED_ACK"], sort=sort, size=size)
    if key == "planned_next":
        return SearchRequest(quick=["OPEN"], filters=[Filter(
            field="work_date", op="eq", value=following.shift_date.isoformat())],
            sort=sort, size=size)
    if key == "important":
        return SearchRequest(quick=["IMPORTANT", "OPEN"], sort=sort, size=size)
    if key == "overdue":
        return SearchRequest(quick=["OVERDUE"], sort=[Sort(field="work_date", dir="asc")],
                             size=size)
    raise ValidationFailed(f"알 수 없는 영역입니다: {key}")


def cockpit(db: Session, actor: User, *, shift_date: date | None = None,
            shift_id: int | None = None, size: int = 50) -> dict[str, Any]:
    window = (window_for(db, shift_date, shift_id) if shift_date and shift_id
              else current_window(db))
    following = next_window(db, window)
    areas = {}
    for key, label in AREAS:
        req = area_request(key, window, following, size)
        page = search_service.run(db, req, actor)
        areas[key] = {"label": label, "total": page.total, "items": page.items,
                      "request": req.model_dump(exclude={"page", "size"})}
    basket = db.scalar(select(ShiftHandover).where(ShiftHandover.from_user_id == actor.id,
                                                   ShiftHandover.status == SESSION_DRAFT))
    in_basket = [i.handover_id for i in basket.items] if basket else []
    return {"window": describe(db, window), "next_window": describe(db, following),
            "areas": areas, "basket_handover_ids": in_basket}


# --------------------------------------------------------------------------- Carry chain

def chain_depth(db: Session, item: ShiftHandoverItem) -> int:
    """이 항목이 몇 교대째 이어서 인계되고 있는가(자기 자신 포함)."""
    depth, current = 1, item.carried_from_item_id
    while current and depth < MAX_CHAIN:
        prev = db.get(ShiftHandoverItem, current)
        if prev is None:
            break
        depth += 1
        current = prev.carried_from_item_id
    return depth


# --------------------------------------------------------------------------- Basket

def _open_codes(db: Session):
    return select(HandoverStatus.code).where(HandoverStatus.category != "CLOSED")


def last_received(db: Session, user_id: int) -> ShiftHandover | None:
    return db.scalar(select(ShiftHandover)
                     .where(ShiftHandover.to_user_id == user_id,
                            ShiftHandover.status.in_((SESSION_SENT, SESSION_CLOSED)))
                     .order_by(ShiftHandover.sent_at.desc(), ShiftHandover.id.desc())
                     .limit(1))


def carry_candidates(db: Session, actor: User) -> list[tuple[ShiftHandoverItem, Handover]]:
    """직전 교대에서 나에게 넘어온 것 중 아직 끝나지 않은 것(B-06)."""
    previous = last_received(db, actor.id)
    if previous is None:
        return []
    rows = db.execute(
        select(ShiftHandoverItem, Handover)
        .join(Handover, Handover.id == ShiftHandoverItem.handover_id)
        .where(ShiftHandoverItem.session_id == previous.id,
               Handover.is_deleted.is_(False),
               Handover.status_code.in_(_open_codes(db)))
        .order_by(ShiftHandoverItem.display_order, ShiftHandoverItem.id)
    ).all()
    return [(item, handover) for item, handover in rows]


def _draft(db: Session, actor: User) -> ShiftHandover | None:
    return db.scalar(select(ShiftHandover).where(ShiftHandover.from_user_id == actor.id,
                                                 ShiftHandover.status == SESSION_DRAFT))


def get_basket(db: Session, actor: User) -> tuple[ShiftHandover, int]:
    """내 Basket(DRAFT 세션). 없으면 만들고, 직전 교대 미완료를 자동으로 담는다.

    Returns: (세션, 이번에 자동으로 담은 건수)
    """
    basket = _draft(db, actor)
    if basket is not None:
        return basket, 0

    window = current_window(db)
    shift = _shift_by_code(db, window.code)
    basket = ShiftHandover(shift_date=window.shift_date, shift_id=shift.id if shift else None,
                           from_user_id=actor.id, status=SESSION_DRAFT)
    db.add(basket)
    db.flush()

    added = 0
    if settings_service.get_value(db, "shift.carry_forward_auto"):
        for order, (prev_item, handover) in enumerate(carry_candidates(db, actor)):
            db.add(ShiftHandoverItem(session_id=basket.id, handover_id=handover.id,
                                     display_order=order, carried_from_item_id=prev_item.id,
                                     is_carry_forward=True, item_note=prev_item.item_note))
            added += 1
        db.flush()
        db.refresh(basket)
    return basket, added


def add_items(db: Session, actor: User, handover_ids: list[int],
              note: str | None = None) -> dict[str, list[int]]:
    basket, _ = get_basket(db, actor)
    existing = {i.handover_id for i in basket.items}
    # 직전에 나에게 넘어온 건이면 Carry Forward 로 이어 붙인다('N교대째' 계산).
    carried = {item.handover_id: item for item, _ in carry_candidates(db, actor)}
    order = max((i.display_order for i in basket.items), default=-1) + 1

    added, skipped = [], []
    for hid in dict.fromkeys(handover_ids):
        handover = db.get(Handover, hid)
        if handover is None or handover.is_deleted or hid in existing:
            skipped.append(hid)
            continue
        prev = carried.get(hid)
        db.add(ShiftHandoverItem(session_id=basket.id, handover_id=hid, display_order=order,
                                 item_note=note, carried_from_item_id=prev.id if prev else None,
                                 is_carry_forward=prev is not None))
        order += 1
        added.append(hid)
    db.flush()
    db.refresh(basket)
    return {"added": added, "skipped": skipped}


def _own_item(db: Session, actor: User, item_id: int) -> tuple[ShiftHandover, ShiftHandoverItem]:
    basket = _draft(db, actor)
    item = db.get(ShiftHandoverItem, item_id)
    if basket is None or item is None or item.session_id != basket.id:
        raise NotFound("Basket 항목을 찾을 수 없습니다.")
    return basket, item


def remove_item(db: Session, actor: User, item_id: int) -> None:
    basket, item = _own_item(db, actor, item_id)
    basket.items.remove(item)
    db.flush()


def update_item(db: Session, actor: User, item_id: int, note: str | None) -> ShiftHandoverItem:
    _, item = _own_item(db, actor, item_id)
    item.item_note = note
    db.flush()
    return item


def update_basket(db: Session, actor: User, changes: dict[str, Any]) -> ShiftHandover:
    basket, _ = get_basket(db, actor)
    if "to_user_id" in changes:
        _check_recipient(db, actor, changes["to_user_id"], required=False)
        basket.to_user_id = changes["to_user_id"]
    if "to_shift_id" in changes:
        if changes["to_shift_id"] is not None and db.get(Shift, changes["to_shift_id"]) is None:
            raise ValidationFailed("존재하지 않는 교대입니다.")
        basket.to_shift_id = changes["to_shift_id"]
    if "summary_note" in changes:
        basket.summary_note = changes["summary_note"]
    if changes.get("order"):
        position = {item_id: i for i, item_id in enumerate(changes["order"])}
        for item in basket.items:
            item.display_order = position.get(item.id, len(position) + item.display_order)
    db.flush()
    db.refresh(basket)
    return basket


def _check_recipient(db: Session, actor: User, user_id: int | None, *, required: bool) -> User | None:
    if user_id is None:
        if required:
            raise ValidationFailed("인계받을 사람을 지정하십시오.", detail={"field": "to_user_id"})
        return None
    if user_id == actor.id:
        raise ValidationFailed("자기 자신에게는 인계할 수 없습니다.", detail={"field": "to_user_id"})
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("인계받을 사용자를 찾을 수 없습니다.", detail={"field": "to_user_id"})
    return user


# --------------------------------------------------------------------------- 전달

def send(db: Session, actor: User, *, to_user_id: int | None, to_shift_id: int | None,
         summary_note: str | None, ctx: RequestContext | None = None) -> ShiftHandover:
    basket = _draft(db, actor)
    if basket is None or not basket.items:
        raise ValidationFailed("Basket 이 비어 있습니다. 인계할 항목을 먼저 담으십시오.")
    recipient = _check_recipient(db, actor, to_user_id if to_user_id is not None
                                 else basket.to_user_id, required=True)

    stamp = now()
    items_detail = []
    for item in basket.items:
        handover = db.get(Handover, item.handover_id)
        if handover is None or handover.is_deleted:
            raise Conflict(f"Basket 에 삭제된 인수인계가 있습니다(#{item.handover_id}). 빼고 다시 보내십시오.",
                           detail={"handover_id": item.handover_id})
        # 전달 당시 내용이 무엇이었는지 증적으로 고정한다.
        item.version_no_at_transfer = handover.current_version_no
        depth = chain_depth(db, item)
        handover.carry_count = depth
        handover.last_transferred_at = stamp
        ack_service.mark_pending(db, handover, recipient.id, session_id=basket.id)
        items_detail.append({"handover_id": handover.id, "version": handover.current_version_no,
                             "carry_depth": depth})

    window = current_window(db)
    shift = _shift_by_code(db, window.code)
    basket.shift_date = window.shift_date
    basket.shift_id = shift.id if shift else basket.shift_id
    basket.to_user_id = recipient.id
    if to_shift_id is not None:
        basket.to_shift_id = to_shift_id
    if summary_note is not None:
        basket.summary_note = summary_note
    basket.status = SESSION_SENT
    basket.sent_at = stamp
    basket.item_count = len(basket.items)
    db.flush()

    carried = sum(1 for d in items_detail if d["carry_depth"] > 1)
    notification_service.notify(
        db, user_id=recipient.id, type_=notification_service.T_TRANSFER,
        title=f"{actor.display_name} 님이 인수인계 {len(items_detail)}건을 전달했습니다",
        body=(f"이어서 인계된 미완료 {carried}건 포함. " if carried else "")
        + (basket.summary_note or ""),
        link_type="SHIFT", link_id=basket.id)
    record(db, action=actions.HANDOVER_TRANSFER, ctx=ctx, user=actor,
           resource_type="SHIFT_HANDOVER", resource_id=basket.id,
           detail={"to_user_id": recipient.id, "count": len(items_detail),
                   "items": items_detail})
    return basket


# --------------------------------------------------------------------------- 이력 / 확인 현황

def session_or_404(db: Session, session_id: int) -> ShiftHandover:
    session = db.get(ShiftHandover, session_id)
    if session is None or session.status == SESSION_DRAFT:
        raise NotFound("인계 기록을 찾을 수 없습니다.")
    return session


def item_views(db: Session, session: ShiftHandover) -> list[dict[str, Any]]:
    """항목마다: 전달 당시 버전 · 지금 버전 · 수신자 확인 상태 · 몇 교대째인지."""
    handover_ids = [i.handover_id for i in session.items]
    acks = {}
    if session.to_user_id and handover_ids:
        acks = {a.handover_id: a for a in db.scalars(select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id.in_(handover_ids),
            HandoverAcknowledgement.user_id == session.to_user_id))}
    out = []
    for item in session.items:
        handover = db.get(Handover, item.handover_id)
        ack = acks.get(item.handover_id)
        out.append({
            "item_id": item.id, "handover_id": item.handover_id,
            "title": handover.title if handover else "(삭제됨)",
            "company": handover.company.name if handover and handover.company else None,
            "status": handover.status.name if handover and handover.status else None,
            "status_category": handover.status.category if handover and handover.status else None,
            "priority": handover.priority.name if handover and handover.priority else None,
            "priority_code": handover.priority_code if handover else None,
            "is_deleted": bool(handover and handover.is_deleted),
            "current_version_no": handover.current_version_no if handover else None,
            "version_no_at_transfer": item.version_no_at_transfer,
            "changed_since_transfer": bool(handover and item.version_no_at_transfer
                                           and handover.current_version_no > item.version_no_at_transfer),
            "item_note": item.item_note, "display_order": item.display_order,
            "is_carry_forward": item.is_carry_forward, "carry_depth": chain_depth(db, item),
            "ack_state": ack.state if ack else None,
            "acked_version_no": ack.acked_version_no if ack else None,
            "acked_at": ack.acked_at if ack else None,
            "stale_reason": ack.stale_reason if ack else None,
        })
    return out


def acked_count(views: list[dict[str, Any]]) -> int:
    return sum(1 for v in views if v["ack_state"] == ACK_ACKED)


def list_sessions(db: Session, *, user_id: int | None = None, direction: str = "all",
                  date_from: date | None = None, date_to: date | None = None,
                  limit: int = 100) -> list[ShiftHandover]:
    stmt = select(ShiftHandover).where(ShiftHandover.status != SESSION_DRAFT)
    if user_id is not None:
        if direction == "sent":
            stmt = stmt.where(ShiftHandover.from_user_id == user_id)
        elif direction == "received":
            stmt = stmt.where(ShiftHandover.to_user_id == user_id)
        else:
            stmt = stmt.where((ShiftHandover.from_user_id == user_id)
                              | (ShiftHandover.to_user_id == user_id))
    if date_from:
        stmt = stmt.where(ShiftHandover.shift_date >= date_from)
    if date_to:
        stmt = stmt.where(ShiftHandover.shift_date <= date_to)
    return list(db.scalars(stmt.order_by(ShiftHandover.sent_at.desc(),
                                         ShiftHandover.id.desc()).limit(limit)))


def close(db: Session, actor: User, session_id: int) -> ShiftHandover:
    """전원 확인된 인계만 닫는다. 확인 안 된 인계를 닫으면 그게 누락이다."""
    session = session_or_404(db, session_id)
    if session.status == SESSION_CLOSED:
        raise Conflict("이미 종료된 인계입니다.")
    if actor.id not in (session.from_user_id, session.to_user_id) \
            and actor.role_code not in ("MANAGER", "ADMIN"):
        raise Forbidden("보낸 사람·받은 사람·관리자만 종료할 수 있습니다.")
    views = item_views(db, session)
    live = [v for v in views if not v["is_deleted"]]
    pending = [v["handover_id"] for v in live if v["ack_state"] != ACK_ACKED]
    if pending:
        raise Conflict(f"아직 확인되지 않은 항목이 {len(pending)}건 있어 종료할 수 없습니다.",
                       detail={"pending_handover_ids": pending})
    session.status = SESSION_CLOSED
    session.closed_at = now()
    session.acked_count = acked_count(views)
    db.flush()
    return session


# --------------------------------------------------------------------------- 인수 확인함

def inbox(db: Session, actor: User) -> list[dict[str, Any]]:
    """내가 확인하거나 다시 확인해야 할 것 — 누가 언제 어느 버전으로 넘겼는지와 함께."""
    rows = db.execute(
        select(HandoverAcknowledgement, Handover)
        .join(Handover, Handover.id == HandoverAcknowledgement.handover_id)
        .where(HandoverAcknowledgement.user_id == actor.id,
               HandoverAcknowledgement.state != ACK_ACKED,
               Handover.is_deleted.is_(False))
        .order_by(HandoverAcknowledgement.updated_at.desc(), HandoverAcknowledgement.id.desc())
    ).all()
    out = []
    for ack, handover in rows:
        session = db.get(ShiftHandover, ack.required_by_session_id) if ack.required_by_session_id else None
        item = None
        if session is not None:
            item = db.scalar(select(ShiftHandoverItem).where(
                ShiftHandoverItem.session_id == session.id,
                ShiftHandoverItem.handover_id == handover.id))
        sender = db.get(User, session.from_user_id) if session else None
        out.append({
            "handover_id": handover.id, "title": handover.title,
            "company": handover.company.name if handover.company else None,
            "status": handover.status.name if handover.status else None,
            "priority_code": handover.priority_code,
            "current_version_no": handover.current_version_no,
            "state": ack.state, "acked_version_no": ack.acked_version_no,
            "stale_reason": ack.stale_reason, "stale_since": ack.stale_since,
            "session_id": session.id if session else None,
            "sent_at": session.sent_at if session else None,
            "from_user": sender.display_name if sender else None,
            "version_no_at_transfer": item.version_no_at_transfer if item else None,
            "item_note": item.item_note if item else None,
            "carry_depth": chain_depth(db, item) if item else None,
        })
    return out


def bulk_acknowledge(db: Session, actor: User, handover_ids: list[int],
                     ctx: RequestContext | None = None) -> dict[str, list[int]]:
    """선택 항목 일괄 확인(FR-C-09). 각 건은 그 순간의 버전으로 기록된다."""
    done, skipped = [], []
    for hid in dict.fromkeys(handover_ids):
        handover = db.get(Handover, hid)
        if handover is None or handover.is_deleted:
            skipped.append(hid)
            continue
        ack_service.acknowledge(db, handover, actor, ctx=ctx)
        done.append(hid)
    return {"acknowledged": done, "skipped": skipped}
