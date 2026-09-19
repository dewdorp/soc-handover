"""인수인계 댓글 (FR-I-05, §65) — 본문 버전과 분리된 대화.

- 댓글은 인수인계 버전을 만들지 않고 재확인도 일으키지 않는다(본문이 아니다).
- 고치기는 쓴 사람만, 지우기는 쓴 사람 또는 handover:update_any(관리자). 지우기는 표시만.
- 쓰기 · 고치기 · 지우기 모두 감사에 남긴다(HANDOVER_COMMENT, detail.op=create|update|delete).
  고치기는 이전 글을 before 에 남긴다 — 댓글도 증적이다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import has_permission
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound
from app.core.time import now
from app.models.handover import Handover, HandoverComment
from app.models.user import User

AUDIT_BODY = 500          # 감사에 남기는 본문 길이


def _handover(db: Session, handover_id: int) -> Handover:
    h = db.get(Handover, handover_id)
    if h is None or h.is_deleted:
        raise NotFound("인수인계를 찾을 수 없습니다.")
    return h


def _comment(db: Session, comment_id: int) -> HandoverComment:
    c = db.get(HandoverComment, comment_id)
    if c is None or c.is_deleted:
        raise NotFound("댓글을 찾을 수 없습니다.")
    return c


def can_edit(actor: User, c: HandoverComment) -> bool:
    return c.author_id == actor.id


def can_delete(actor: User, c: HandoverComment) -> bool:
    return c.author_id == actor.id or has_permission(actor.role_code, "handover:update_any")


def list_for(db: Session, handover_id: int) -> list[HandoverComment]:
    _handover(db, handover_id)
    return list(db.scalars(select(HandoverComment)
                           .where(HandoverComment.handover_id == handover_id,
                                  HandoverComment.is_deleted.is_(False))
                           .order_by(HandoverComment.created_at, HandoverComment.id)))


def count_for(db: Session, handover_id: int) -> int:
    return db.scalar(select(func.count()).select_from(HandoverComment)
                     .where(HandoverComment.handover_id == handover_id,
                            HandoverComment.is_deleted.is_(False))) or 0


def create(db: Session, actor: User, handover_id: int, body: str,
           ctx: RequestContext | None = None) -> HandoverComment:
    h = _handover(db, handover_id)
    c = HandoverComment(handover_id=h.id, author_id=actor.id, body=body.strip())
    db.add(c)
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=h.id, after={"body": c.body[:AUDIT_BODY]},
           detail={"op": "create", "comment_id": c.id})
    return c


def update(db: Session, actor: User, comment_id: int, body: str,
           ctx: RequestContext | None = None) -> HandoverComment:
    c = _comment(db, comment_id)
    if not can_edit(actor, c):
        raise Forbidden("본인이 쓴 댓글만 고칠 수 있습니다.")
    new = body.strip()
    if new == c.body:
        return c
    before = c.body
    c.body, c.is_edited, c.edited_at = new, True, now()
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=c.handover_id, before={"body": before[:AUDIT_BODY]},
           after={"body": new[:AUDIT_BODY]}, detail={"op": "update", "comment_id": c.id})
    return c


def delete(db: Session, actor: User, comment_id: int, ctx: RequestContext | None = None) -> None:
    c = _comment(db, comment_id)
    if not can_delete(actor, c):
        raise Forbidden("본인이 쓴 댓글만 지울 수 있습니다(관리자 제외).")
    c.is_deleted, c.deleted_at, c.deleted_by = True, now(), actor.id
    db.flush()
    record(db, action=actions.HANDOVER_COMMENT, ctx=ctx, user=actor, resource_type="HANDOVER",
           resource_id=c.handover_id, before={"body": c.body[:AUDIT_BODY]},
           detail={"op": "delete", "comment_id": c.id, "author_id": c.author_id})


def to_out(db: Session, actor: User, c: HandoverComment) -> dict[str, Any]:
    author = db.get(User, c.author_id) if c.author_id else None
    return {"id": c.id, "handover_id": c.handover_id, "body": c.body, "author_id": c.author_id,
            "author": author.display_name if author else None, "created_at": c.created_at,
            "is_edited": c.is_edited, "edited_at": c.edited_at,
            "can_edit": can_edit(actor, c), "can_delete": can_delete(actor, c)}
