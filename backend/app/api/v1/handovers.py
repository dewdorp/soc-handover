"""인수인계 라우터. 비즈니스 규칙은 services/handover_service.py 에 있다.

목록은 Phase 2 기준의 단순 조회다. Column Filter DSL / Facet / FTS 는 Phase 3 에서
`POST /handovers/search` 로 추가하며, 그때 이 GET 은 동일 DSL 의 query 인코딩 형태가 된다.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import get_current_user, require, require_password_changed
from app.auth.rbac import has_permission
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import NotFound, ValidationFailed
from app.core.pagination import Page, PageParams
from app.core.time import today
from app.models.handover import Handover, HandoverAcknowledgement, HandoverStar
from app.models.user import User
from app.schemas.handover import (AcknowledgeRequest, AckOut, AsOfOut, DeleteRequest, DiffOut,
                                  HandoverCreate, HandoverDetail, HandoverListItem,
                                  HandoverUpdate, PinRequest, RestoreRequest, TimelineEvent,
                                  VersionDetail, VersionSummary)
from app.services import ack_service, handover_service

router = APIRouter(tags=["handovers"], dependencies=[Depends(require_password_changed)])

_SORTABLE = {
    "registered_date": Handover.registered_date,
    "work_date": Handover.work_date,
    "updated_at": Handover.updated_at,
    "created_at": Handover.created_at,
    "title": Handover.title,
    "id": Handover.id,
}


# --------------------------------------------------------------------------- 직렬화

def _base_fields(h: Handover) -> dict:
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


def _list_item(h: Handover, *, my_ack: str | None, starred: bool) -> HandoverListItem:
    return HandoverListItem.model_validate(
        {**_base_fields(h), "my_ack_state": my_ack, "is_starred": starred}
    )


def _detail(db: Session, h: Handover, actor: User) -> HandoverDetail:
    acks = ack_service.list_for_handover(db, h.id)
    mine = next((a for a in acks if a.user_id == actor.id), None)
    return HandoverDetail.model_validate({
        **_base_fields(h),
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
        "acknowledgements": [
            AckOut.model_validate({
                "user_id": a.user_id, "user": None, "state": a.state,
                "acked_version_no": a.acked_version_no, "acked_at": a.acked_at,
                "stale_since": a.stale_since, "stale_reason": a.stale_reason, "note": a.note,
            }) for a in acks
        ],
    })


# --------------------------------------------------------------------------- 목록 / 생성

@router.get("/handovers", response_model=Page[HandoverListItem])
def list_handovers(
    q: str = Query(default="", max_length=200),
    company_id: int | None = None,
    status_code: str | None = None,
    priority_code: str | None = None,
    assignee_id: int | None = None,
    is_important: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_deleted: bool = False,
    sort: str = Query(default="registered_date:desc", max_length=100),
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
    actor: User = Depends(require("handover:read")),
):
    params = PageParams(page=page, size=size)
    stmt = select(Handover)

    if include_deleted:
        if not has_permission(actor.role_code, "handover:read_deleted"):
            raise ValidationFailed("삭제된 항목을 조회할 권한이 없습니다.")
    else:
        stmt = stmt.where(Handover.is_deleted.is_(False))

    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Handover.title.ilike(like), Handover.content.ilike(like),
                              Handover.search_text.ilike(like)))
    if company_id is not None:
        stmt = stmt.where(Handover.company_id == company_id)
    if status_code:
        stmt = stmt.where(Handover.status_code == status_code)
    if priority_code:
        stmt = stmt.where(Handover.priority_code == priority_code)
    if assignee_id is not None:
        stmt = stmt.where(Handover.assignee_id == assignee_id)
    if is_important is not None:
        stmt = stmt.where(Handover.is_important.is_(is_important))
    if date_from is not None:
        stmt = stmt.where(Handover.registered_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Handover.registered_date <= date_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    total_all = db.scalar(
        select(func.count()).select_from(Handover).where(Handover.is_deleted.is_(False))
    ) or 0

    # 상단고정은 항상 위로. 그다음 사용자가 지정한 정렬.
    order = [Handover.is_pinned.desc()]
    for token in sort.split(","):
        name, _, direction = token.partition(":")
        column = _SORTABLE.get(name.strip())
        if column is None:
            continue
        order.append(column.desc() if direction.strip().lower() == "desc" else column.asc())
    order.append(Handover.id.desc())

    rows = list(db.scalars(stmt.order_by(*order).offset(params.offset).limit(params.size)))
    ids = [r.id for r in rows]

    my_acks: dict[int, str] = {}
    starred: set[int] = set()
    if ids:
        my_acks = {
            hid: state for hid, state in db.execute(
                select(HandoverAcknowledgement.handover_id, HandoverAcknowledgement.state)
                .where(HandoverAcknowledgement.handover_id.in_(ids),
                       HandoverAcknowledgement.user_id == actor.id)
            )
        }
        starred = set(db.scalars(
            select(HandoverStar.handover_id)
            .where(HandoverStar.handover_id.in_(ids), HandoverStar.user_id == actor.id)
        ))

    items = [_list_item(r, my_ack=my_acks.get(r.id), starred=r.id in starred) for r in rows]
    return Page.of(items, params, total, total_all=total_all)


@router.post("/handovers", response_model=HandoverDetail, status_code=status.HTTP_201_CREATED)
def create_handover(payload: HandoverCreate, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:create")),
                    ctx: RequestContext = Depends(get_context)):
    data = payload.model_dump()
    if data.get("registered_date") is None:
        data["registered_date"] = today()
    handover = handover_service.create_handover(db, data, actor, ctx)
    return _detail(db, handover, actor)


# --------------------------------------------------------------------------- 단건

@router.get("/handovers/{handover_id}", response_model=HandoverDetail | AsOfOut)
def get_handover(handover_id: int, as_of: datetime | None = None,
                 db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:read"))):
    handover = handover_service.get_or_404(db, handover_id, actor)
    if as_of is None:
        return _detail(db, handover, actor)

    version = handover_service.as_of(db, handover_id, as_of)
    if version is None:
        raise NotFound("해당 시각에는 아직 존재하지 않던 인수인계입니다.")
    return AsOfOut(handover_id=handover_id, as_of=as_of, version_no=version.version_no,
                   change_type=version.change_type, changed_at=version.changed_at,
                   data=version.after_data)


@router.patch("/handovers/{handover_id}", response_model=HandoverDetail)
def update_handover(handover_id: int, payload: HandoverUpdate, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:update_own")),
                    ctx: RequestContext = Depends(get_context)):
    handover, _created = handover_service.update_handover(
        db, handover_id, payload.changes(), expected_version=payload.expected_version,
        change_reason=payload.change_reason, actor=actor, ctx=ctx)
    return _detail(db, handover, actor)


@router.delete("/handovers/{handover_id}", response_model=HandoverDetail)
def delete_handover(handover_id: int, payload: DeleteRequest, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:delete")),
                    ctx: RequestContext = Depends(get_context)):
    handover = handover_service.soft_delete(db, handover_id, payload.reason, actor, ctx)
    return _detail(db, handover, actor)


@router.post("/handovers/{handover_id}/undelete", response_model=HandoverDetail)
def undelete_handover(handover_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(require("handover:undelete")),
                      ctx: RequestContext = Depends(get_context)):
    handover = handover_service.undelete(db, handover_id, actor, ctx)
    return _detail(db, handover, actor)


# --------------------------------------------------------------------------- 즐겨찾기 / 고정

@router.post("/handovers/{handover_id}/star", status_code=status.HTTP_204_NO_CONTENT)
def add_star(handover_id: int, db: Session = Depends(get_db),
             actor: User = Depends(require("handover:star"))):
    handover_service.get_or_404(db, handover_id, actor)
    handover_service.set_star(db, handover_id, actor.id, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/handovers/{handover_id}/star", status_code=status.HTTP_204_NO_CONTENT)
def remove_star(handover_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:star"))):
    handover_service.get_or_404(db, handover_id, actor)
    handover_service.set_star(db, handover_id, actor.id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/handovers/{handover_id}/pin", response_model=HandoverDetail)
def set_pin(handover_id: int, payload: PinRequest, db: Session = Depends(get_db),
            actor: User = Depends(require("handover:pin")),
            ctx: RequestContext = Depends(get_context)):
    """전역 상단고정. is_pinned 는 버전 관리 대상이므로 일반 수정 경로를 그대로 탄다."""
    current = handover_service.get_or_404(db, handover_id, actor)
    handover, _ = handover_service.update_handover(
        db, handover_id, {"is_pinned": payload.pinned},
        expected_version=current.current_version_no,
        change_reason="상단고정 변경", actor=actor, ctx=ctx)
    return _detail(db, handover, actor)


# --------------------------------------------------------------------------- Version

@router.get("/handovers/{handover_id}/versions", response_model=list[VersionSummary])
def list_versions(handover_id: int, db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    handover_service.get_or_404(db, handover_id, actor)
    return handover_service.list_versions(db, handover_id)


@router.get("/handovers/{handover_id}/versions/diff", response_model=DiffOut)
def diff_versions(handover_id: int, from_: int = Query(alias="from", ge=1),
                  to: int = Query(ge=1), db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    handover_service.get_or_404(db, handover_id, actor)
    return handover_service.diff_versions(db, handover_id, from_, to)


@router.get("/handovers/{handover_id}/versions/{version_no}", response_model=VersionDetail)
def get_version(handover_id: int, version_no: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:read"))):
    handover_service.get_or_404(db, handover_id, actor)
    return handover_service.get_version(db, handover_id, version_no)


@router.post("/handovers/{handover_id}/versions/{version_no}/restore",
             response_model=HandoverDetail)
def restore_version(handover_id: int, version_no: int, payload: RestoreRequest,
                    db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:update_own")),
                    ctx: RequestContext = Depends(get_context)):
    handover = handover_service.restore_version(
        db, handover_id, version_no, expected_version=payload.expected_version,
        change_reason=payload.change_reason, actor=actor, ctx=ctx)
    return _detail(db, handover, actor)


@router.get("/handovers/{handover_id}/timeline", response_model=list[TimelineEvent])
def get_timeline(handover_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:read"))):
    handover_service.get_or_404(db, handover_id, actor)
    return handover_service.timeline(db, handover_id)


# --------------------------------------------------------------------------- 확인(Ack)

@router.get("/handovers/{handover_id}/acknowledgements", response_model=list[AckOut])
def list_acknowledgements(handover_id: int, db: Session = Depends(get_db),
                          actor: User = Depends(require("handover:read"))):
    handover_service.get_or_404(db, handover_id, actor)
    return ack_service.list_for_handover(db, handover_id)


@router.post("/handovers/{handover_id}/acknowledge", response_model=AckOut)
def acknowledge(handover_id: int, payload: AcknowledgeRequest, db: Session = Depends(get_db),
                actor: User = Depends(require("ack:write")),
                ctx: RequestContext = Depends(get_context)):
    handover = handover_service.get_or_404(db, handover_id, actor)
    return ack_service.acknowledge(db, handover, actor, note=payload.note, ctx=ctx)


@router.get("/acknowledgements/pending", response_model=list[AckOut])
def pending_acknowledgements(db: Session = Depends(get_db),
                             actor: User = Depends(get_current_user)):
    """내가 확인/재확인해야 할 목록(FR-C-04 미확인 배너)."""
    from app.models.handover import ACK_PENDING, ACK_REACK

    rows = db.scalars(
        select(HandoverAcknowledgement)
        .join(Handover, Handover.id == HandoverAcknowledgement.handover_id)
        .where(HandoverAcknowledgement.user_id == actor.id,
               HandoverAcknowledgement.state.in_((ACK_PENDING, ACK_REACK)),
               Handover.is_deleted.is_(False))
        .order_by(HandoverAcknowledgement.id)
    ).all()
    return list(rows)


@router.post("/handovers/{handover_id}/view", status_code=status.HTTP_204_NO_CONTENT)
def mark_viewed(handover_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:read")),
                ctx: RequestContext = Depends(get_context)):
    """상세 열람 감사 기록(§60 HANDOVER_VIEW). 조회 자체를 막지 않기 위해 별도 엔드포인트로 둔다."""
    handover_service.get_or_404(db, handover_id, actor)
    record(db, action=actions.HANDOVER_VIEW, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
