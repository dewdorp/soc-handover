"""인수인계 라우터. 비즈니스 규칙은 services/handover_service.py 에 있다.

목록(GET)은 링크 공유용 단순 형태이고, 실제 실행은 POST /handovers/search 와 동일한
필터 DSL 을 지난다(services/search_service.run). 두 경로의 결과가 어긋날 수 없다.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.api.v1 import handover_serde
from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import get_current_user, require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.pagination import Page
from app.core.time import today
from app.models.handover import Handover, HandoverAcknowledgement
from app.models.user import User
from app.schemas.handover import (AcknowledgeRequest, AckOut, AsOfOut, DeleteRequest, DiffOut,
                                  HandoverCreate, HandoverDetail, HandoverListItem,
                                  HandoverUpdate, PinRequest, RestoreRequest, TimelineEvent,
                                  VersionDetail, VersionSummary)
from app.search.dsl import Filter, SearchRequest, Sort
from app.services import ack_service, handover_service, search_service

router = APIRouter(tags=["handovers"], dependencies=[Depends(require_password_changed)])


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
    quick: str = Query(default="", max_length=200,
                       description="쉼표 구분 Quick Filter 토큰(TODAY,MINE,OPEN,...)"),
    include_deleted: bool = False,
    sort: str = Query(default="registered_date:desc", max_length=100),
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
    actor: User = Depends(require("handover:read")),
):
    """링크 공유용 단순 조회. 내부적으로는 POST /handovers/search 와 같은 DSL 로 변환된다."""
    filters: list[Filter] = []
    for field, value in (("company_id", company_id), ("status_code", status_code),
                         ("priority_code", priority_code), ("assignee_id", assignee_id),
                         ("is_important", is_important)):
        if value is not None and value != "":
            filters.append(Filter(field=field, op="eq", value=value))
    if date_from is not None:
        filters.append(Filter(field="registered_date", op="gte", value=date_from.isoformat()))
    if date_to is not None:
        filters.append(Filter(field="registered_date", op="lte", value=date_to.isoformat()))

    sorts = []
    for token in sort.split(","):
        name, _, direction = token.partition(":")
        if name.strip():
            sorts.append(Sort(field=name.strip(),
                              dir="desc" if direction.strip().lower() == "desc" else "asc"))

    request = SearchRequest(
        q=q or None, filters=filters, sort=sorts,
        quick=[t.strip() for t in quick.split(",") if t.strip()],
        page=page, size=size, include_deleted=include_deleted)
    return search_service.run(db, request, actor)


@router.post("/handovers", response_model=HandoverDetail, status_code=status.HTTP_201_CREATED)
def create_handover(payload: HandoverCreate, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:create")),
                    ctx: RequestContext = Depends(get_context)):
    data = payload.model_dump()
    if data.get("registered_date") is None:
        data["registered_date"] = today()
    handover = handover_service.create_handover(db, data, actor, ctx)
    return handover_serde.detail(db, handover, actor)


# --------------------------------------------------------------------------- 단건

@router.get("/handovers/{handover_id}", response_model=HandoverDetail | AsOfOut)
def get_handover(handover_id: int, as_of: datetime | None = None,
                 db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:read"))):
    handover = handover_service.get_or_404(db, handover_id, actor)
    if as_of is None:
        return handover_serde.detail(db, handover, actor)

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
    return handover_serde.detail(db, handover, actor)


@router.delete("/handovers/{handover_id}", response_model=HandoverDetail)
def delete_handover(handover_id: int, payload: DeleteRequest, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:delete")),
                    ctx: RequestContext = Depends(get_context)):
    handover = handover_service.soft_delete(db, handover_id, payload.reason, actor, ctx)
    return handover_serde.detail(db, handover, actor)


@router.post("/handovers/{handover_id}/undelete", response_model=HandoverDetail)
def undelete_handover(handover_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(require("handover:undelete")),
                      ctx: RequestContext = Depends(get_context)):
    handover = handover_service.undelete(db, handover_id, actor, ctx)
    return handover_serde.detail(db, handover, actor)


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
    return handover_serde.detail(db, handover, actor)


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
    return handover_serde.detail(db, handover, actor)


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
               Handover.is_deleted == false())
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
