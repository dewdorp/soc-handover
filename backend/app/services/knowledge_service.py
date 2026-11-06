"""SOC 운영 지식: 그룹별 공개, 검색, 문서 버전 충돌 방지."""
from __future__ import annotations

from typing import Any

from sqlalchemy import exists, false, func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.models.group import Group, UserGroup, VIS_ALL, VIS_GROUPS
from app.models.knowledge import KnowledgeArticle, KnowledgeGroup
from app.models.user import User
from app.services import group_service

CATEGORIES = ("운영 절차", "탐지·분석", "비상 대응", "장비·솔루션",
              "점검 체크리스트", "참고 자료")
MANAGERS = {"ADMIN", "MANAGER"}


def visible_clause(actor: User):
    """관리자라도 공개 그룹에 속하지 않으면 열람할 수 없다."""
    return or_(
        KnowledgeArticle.visibility == VIS_ALL,
        KnowledgeArticle.created_by == actor.id,
        exists(
            select(KnowledgeGroup.id)
            .join(Group, Group.id == KnowledgeGroup.group_id)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(KnowledgeGroup.article_id == KnowledgeArticle.id,
                   UserGroup.user_id == actor.id, Group.is_active.is_(True))
            .correlate(KnowledgeArticle)
        ),
    )


def get_or_404(db: Session, actor: User, article_id: int) -> KnowledgeArticle:
    row = db.scalar(select(KnowledgeArticle).where(
        KnowledgeArticle.id == article_id,
        KnowledgeArticle.is_deleted == false(),
        visible_clause(actor),
    ))
    if row is None:
        raise NotFound("운영 지식을 찾을 수 없습니다.")
    return row


def can_edit(actor: User, row: KnowledgeArticle) -> bool:
    return row.created_by == actor.id or actor.role_code in MANAGERS


def _scope(db: Session, row: KnowledgeArticle, actor: User, visibility: str,
           group_ids: list[int]) -> None:
    wanted = {int(v) for v in group_ids}
    if visibility == VIS_ALL or not wanted:
        row.visibility = VIS_ALL
        row.group_links.clear()
        db.flush()
        return
    if visibility != VIS_GROUPS:
        raise ValidationFailed("운영 지식 공개 범위 값이 잘못됐습니다.")
    permitted = set(group_service.my_group_ids(db, actor.id))
    if not wanted <= permitted:
        raise ValidationFailed("내가 속하지 않은 그룹에는 운영 지식을 공개할 수 없습니다.")
    active = set(db.scalars(select(Group.id).where(
        Group.id.in_(wanted), Group.is_active.is_(True))).all())
    if active != wanted:
        raise ValidationFailed("사용 중지된 그룹에는 공개할 수 없습니다.")
    existing = {link.group_id: link for link in row.group_links}
    for gid, link in existing.items():
        if gid not in wanted:
            row.group_links.remove(link)
    for gid in sorted(wanted - set(existing)):
        row.group_links.append(KnowledgeGroup(group_id=gid))
    row.visibility = VIS_GROUPS
    db.flush()


def to_out(db: Session, actor: User, row: KnowledgeArticle) -> dict[str, Any]:
    return {
        "id": row.id, "category": row.category, "title": row.title, "body": row.body,
        "visibility": row.visibility, "group_ids": sorted(x.group_id for x in row.group_links),
        "is_pinned": row.is_pinned, "review_due": row.review_due, "version_no": row.version_no,
        "created_by": row.created_by, "updated_by": row.updated_by,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "can_edit": can_edit(actor, row),
    }


def list_for(db: Session, actor: User, q: str | None = None, category: str | None = None,
             offset: int = 0, limit: int = 50) -> list[KnowledgeArticle]:
    stmt = select(KnowledgeArticle).where(
        KnowledgeArticle.is_deleted == false(), visible_clause(actor))
    if q:
        term = q.strip()
        if term:
            stmt = stmt.where(or_(KnowledgeArticle.title.ilike(f"%{term}%"),
                                  KnowledgeArticle.body.ilike(f"%{term}%")))
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    return list(db.scalars(stmt.order_by(KnowledgeArticle.is_pinned.desc(),
                                         KnowledgeArticle.updated_at.desc(),
                                         KnowledgeArticle.id.desc())
                           .offset(offset).limit(limit)))


def create(db: Session, actor: User, data: dict[str, Any],
           ctx: RequestContext | None = None) -> KnowledgeArticle:
    title = (data["title"] or "").strip()
    if not title:
        raise ValidationFailed("제목을 입력하십시오.")
    row = KnowledgeArticle(
        title=title, category=data["category"], body=data.get("body") or "",
        is_pinned=bool(data.get("is_pinned")), review_due=data.get("review_due"),
        created_by=actor.id, updated_by=actor.id, version_no=1,
    )
    db.add(row)
    db.flush()
    _scope(db, row, actor, data.get("visibility") or VIS_ALL, data.get("group_ids") or [])
    record(db, action=actions.KNOWLEDGE_CREATE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id,
           after={"title": title, "visibility": row.visibility,
                  "group_ids": [x.group_id for x in row.group_links]})
    return row


def edit(db: Session, actor: User, article_id: int, changes: dict[str, Any],
         ctx: RequestContext | None = None) -> KnowledgeArticle:
    row = get_or_404(db, actor, article_id)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 수정할 수 있습니다.")
    expected = changes.pop("version_no")
    if row.version_no != expected:
        raise VersionConflict("다른 사람이 수정했습니다. 다시 불러온 뒤 수정하십시오.")
    title = (changes.get("title") if changes.get("title") is not None else row.title).strip()
    if not title:
        raise ValidationFailed("제목을 입력하십시오.")
    visibility = changes.get("visibility") or row.visibility
    gids = changes.get("group_ids")
    if gids is None:
        gids = [x.group_id for x in row.group_links]
    # 버전 비교와 갱신을 한 SQL 문으로 처리해 동시 편집 덮어쓰기를 방지한다.
    vals = {k: v for k, v in changes.items() if k in (
        "category", "body", "is_pinned", "review_due") and v is not None}
    vals.update(title=title, updated_by=actor.id, version_no=expected + 1)
    result = db.execute(update(KnowledgeArticle).where(
        KnowledgeArticle.id == article_id, KnowledgeArticle.version_no == expected
    ).values(**vals).execution_options(synchronize_session="fetch"))
    if result.rowcount != 1:
        raise VersionConflict("다른 사람이 수정했습니다. 다시 불러온 뒤 수정하십시오.")
    db.refresh(row)
    _scope(db, row, actor, visibility, gids)
    record(db, action=actions.KNOWLEDGE_UPDATE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id,
           after={"version_no": row.version_no, "title": row.title, "visibility": row.visibility,
                  "group_ids": [x.group_id for x in row.group_links]})
    return row


def delete(db: Session, actor: User, article_id: int,
           ctx: RequestContext | None = None) -> None:
    row = get_or_404(db, actor, article_id)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 삭제할 수 있습니다.")
    row.is_deleted = True
    db.flush()
    record(db, action=actions.KNOWLEDGE_DELETE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id, before={"title": row.title})
