"""인수인계 댓글 (FR-I-05, §65) — 본문 버전과 분리된 대화.

- 댓글은 인수인계 버전을 만들지 않고 재확인도 일으키지 않는다(본문이 아니다).
- 고치기는 쓴 사람만, 지우기는 쓴 사람 또는 handover:update_any(관리자). 지우기는 표시만.
- 쓰기 · 고치기 · 지우기 모두 감사에 남긴다(HANDOVER_COMMENT, detail.op=create|update|delete).
  고치기는 이전 글을 before 에 남긴다 — 댓글도 증적이다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import has_permission
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import now
from app.services import rich_body
from app.models.handover import Handover, HandoverComment
from app.models.user import User

AUDIT_BODY = 500          # 감사에 남기는 본문 길이
#: 댓글 순수 텍스트 상한. 표를 넣으면 칸 글자가 모두 들어가므로 입력칸(5,000자)보다 넉넉히.
MAX_COMMENT_TEXT = 20_000


def _handover(db: Session, handover_id: int, actor: User) -> Handover:
    """원문을 볼 수 없는 사람에게는 댓글도 보이지 않는다 — 댓글은 그 업무의 내용이다."""
    from app.services import group_service

    h = db.get(Handover, handover_id)
    if h is None or h.is_deleted:
        raise NotFound("인수인계를 찾을 수 없습니다.")
    group_service.assert_visible(db, h, actor)
    return h


def _comment(db: Session, comment_id: int, actor: User) -> HandoverComment:
    c = db.get(HandoverComment, comment_id)
    if c is None or c.is_deleted:
        raise NotFound("댓글을 찾을 수 없습니다.")
    _handover(db, c.handover_id, actor)     # 원문 열람 범위를 먼저 확인한다
    return c


def can_edit(actor: User, c: HandoverComment) -> bool:
    return c.author_id == actor.id


def can_delete(actor: User, c: HandoverComment) -> bool:
    return c.author_id == actor.id or has_permission(actor.role_code, "handover:update_any")


def list_for(db: Session, handover_id: int, actor: User) -> list[HandoverComment]:
    _handover(db, handover_id, actor)
    return list(db.scalars(select(HandoverComment)
                           .where(HandoverComment.handover_id == handover_id,
                                  HandoverComment.is_deleted == false())
                           .order_by(HandoverComment.created_at, HandoverComment.id)))


def count_for(db: Session, handover_id: int) -> int:
    return db.scalar(select(func.count()).select_from(HandoverComment)
                     .where(HandoverComment.handover_id == handover_id,
                            HandoverComment.is_deleted == false())) or 0


def create(db: Session, actor: User, handover_id: int, body: str,
           ctx: RequestContext | None = None, *,
           body_doc: dict[str, Any] | None = None) -> HandoverComment:
    """댓글은 인계 원문과 따로다 — 버전도 인수 확인도 건드리지 않는다.

    댓글에 붙인 그림은 그 인계에 묶여, 인계를 볼 수 있는 사람만 본다.
    """
    h = _handover(db, handover_id, actor)
    text, doc = rich_body.prepare(db, actor, text=body, doc=body_doc, entity_type="HANDOVER",
                                  entity_id=h.id, max_text=MAX_COMMENT_TEXT)
    if not text:
        raise ValidationFailed("댓글 내용을 입력하십시오.")
    c = HandoverComment(handover_id=h.id, author_id=actor.id, body=text, body_doc=doc)
    db.add(c)
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=h.id, after={"body": c.body[:AUDIT_BODY]},
           detail={"op": "create", "comment_id": c.id})
    return c


def update(db: Session, actor: User, comment_id: int, body: str,
           ctx: RequestContext | None = None, *,
           body_doc: dict[str, Any] | None = None) -> HandoverComment:
    c = _comment(db, comment_id, actor)
    if not can_edit(actor, c):
        raise Forbidden("본인이 쓴 댓글만 고칠 수 있습니다.")
    new, doc = rich_body.prepare(db, actor, text=body, doc=body_doc, entity_type="HANDOVER",
                                 entity_id=c.handover_id, max_text=MAX_COMMENT_TEXT)
    if not new:
        raise ValidationFailed("댓글 내용을 입력하십시오.")
    if new == c.body and doc == c.body_doc:
        return c
    before = c.body
    c.body, c.body_doc, c.is_edited, c.edited_at = new, doc, True, now()
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=c.handover_id, before={"body": before[:AUDIT_BODY]},
           after={"body": new[:AUDIT_BODY]}, detail={"op": "update", "comment_id": c.id})
    return c


def delete(db: Session, actor: User, comment_id: int, ctx: RequestContext | None = None) -> None:
    c = _comment(db, comment_id, actor)
    if not can_delete(actor, c):
        raise Forbidden("본인이 쓴 댓글만 지울 수 있습니다(관리자 제외).")
    c.is_deleted, c.deleted_at, c.deleted_by = True, now(), actor.id
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=c.handover_id, before={"body": c.body[:AUDIT_BODY]},
           detail={"op": "delete", "comment_id": c.id, "author_id": c.author_id})


def to_out(db: Session, actor: User, c: HandoverComment) -> dict[str, Any]:
    author = db.get(User, c.author_id) if c.author_id else None
    return {"id": c.id, "handover_id": c.handover_id, "body": c.body, "body_doc": c.body_doc,
            "author_id": c.author_id,
            "author": author.display_name if author else None, "created_at": c.created_at,
            "is_edited": c.is_edited, "edited_at": c.edited_at,
            "can_edit": can_edit(actor, c), "can_delete": can_delete(actor, c)}
