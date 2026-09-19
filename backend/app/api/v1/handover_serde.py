"""ORM → 응답 스키마 변환. 목록 라우터와 검색 라우터가 같은 표현을 쓰도록 한 곳에 둔다.

목록 한 페이지의 '내 확인상태'와 '즐겨찾기'는 행마다 조회하면 N+1 이 된다.
여기서 페이지 단위로 한 번에 모아 온다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.handover import Handover, HandoverAcknowledgement, HandoverStar
from app.models.user import User
from app.schemas.handover import AckOut, HandoverDetail, HandoverListItem
from app.services import ack_service, handover_service, schedule_service, task_service


def base_fields(h: Handover) -> dict:
    return {
        "id": h.id,
        "company": h.company,
        "title": h.title,
        "status": h.status,
        "priority": h.priority,
        "registered_date": h.registered_date,
        "work_date": h.work_date,
        "completed_at": h.completed_at,
        "sender": h.sender,
        "sender_name_raw": h.sender_name_raw,
        "assignee": h.assignee,
        "assignee_name_raw": h.assignee_name_raw,
        "checker": h.checker,
        "checker_name_raw": h.checker_name_raw,
        "is_important": h.is_important,
        "is_pinned": h.is_pinned,
        "is_recurring": h.is_recurring,
        "current_version_no": h.current_version_no,
        "ack_state_cache": h.ack_state_cache,
        "tags": handover_service.tag_names(h),
        "carry_count": h.carry_count,
        "updated_at": h.updated_at,
        "is_deleted": h.is_deleted,
    }


def list_item(h: Handover, *, my_ack: str | None, starred: bool) -> HandoverListItem:
    return HandoverListItem.model_validate(
        {**base_fields(h), "my_ack_state": my_ack, "is_starred": starred})


def list_items(db: Session, rows: list[Handover], user_id: int) -> list[HandoverListItem]:
    """페이지 단위로 내 확인상태·즐겨찾기를 한 번에 붙인다."""
    ids = [r.id for r in rows]
    if not ids:
        return []
    my_acks = {
        hid: state for hid, state in db.execute(
            select(HandoverAcknowledgement.handover_id, HandoverAcknowledgement.state)
            .where(HandoverAcknowledgement.handover_id.in_(ids),
                   HandoverAcknowledgement.user_id == user_id))
    }
    starred = set(db.scalars(
        select(HandoverStar.handover_id)
        .where(HandoverStar.handover_id.in_(ids), HandoverStar.user_id == user_id)))
    return [list_item(r, my_ack=my_acks.get(r.id), starred=r.id in starred) for r in rows]


def detail(db: Session, h: Handover, actor: User) -> HandoverDetail:
    acks = ack_service.list_for_handover(db, h.id)
    mine = next((a for a in acks if a.user_id == actor.id), None)
    return HandoverDetail.model_validate({
        **base_fields(h),
        "my_ack_state": mine.state if mine else None,
        "is_starred": handover_service.is_starred(db, h.id, actor.id),
        "content": h.content,
        "remark": h.remark,
        "created_by": h.created_by,
        "updated_by": h.updated_by,
        "created_at": h.created_at,
        "deleted_at": h.deleted_at,
        "deleted_by": h.deleted_by,
        "delete_reason": h.delete_reason,
        "source_file": h.source_file,
        "source_sheet": h.source_sheet,
        "source_row": h.source_row,
        "task_count": task_service.count_for_handover(db, h.id),
        "schedule_count": schedule_service.count_for_handover(db, h.id),
        "acknowledgements": [
            AckOut.model_validate({
                "user_id": a.user_id, "user": db.get(User, a.user_id), "state": a.state,
                "acked_version_no": a.acked_version_no, "acked_at": a.acked_at,
                "stale_since": a.stale_since, "stale_reason": a.stale_reason, "note": a.note,
            }) for a in acks
        ],
    })
