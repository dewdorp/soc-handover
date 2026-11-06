"""SOC 운영 지식: 그룹별 공개, 검색, 개정 이력, 인수인계 연계.

열람 판정은 group_service 와 같은 원칙을 따른다 — 역할은 '무엇을 할 수 있는가'이고
그룹은 '무엇을 볼 수 있는가'다. 관리자라도 자기 그룹이 아닌 문서의 본문은 못 본다.
첨부는 attachment_service 가 이 모듈의 get_or_404 를 그대로 불러 판정한다.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, exists, false, func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.core.time import now
from app.models.group import VIS_ALL, VIS_GROUPS, Group, UserGroup
from app.models.handover import Handover
from app.models.knowledge import (KnowledgeArticle, KnowledgeGroup, KnowledgeHandoverLink,
                                  KnowledgeRevision, KnowledgeTag)
from app.models.user import User
from app.services import group_service

CATEGORIES = ("운영 절차", "탐지·분석", "비상 대응", "장비·솔루션",
              "점검 체크리스트", "참고 자료")
MANAGERS = {"ADMIN", "MANAGER"}

#: 새 문서를 열면 이 뼈대가 들어간다. 빈 화면 앞에서 멈추지 않게 하고,
#: 사람마다 다른 순서로 적어 뒤에 읽는 사람이 헤매는 것을 막는다(§4 표준 양식).
TEMPLATE = """## 1. 목적 · 범위
(이 절차가 다루는 대상과, 다루지 않는 것)

## 2. 탐지 · 확인 기준
(어떤 이벤트·조건일 때 이 절차를 쓰는가 — 룰 이름, 임계치, 예시 로그)

## 3. 분석 절차
1.
2.
3.

## 4. 조치 방법
(차단·격리·계정 조치. 되돌리는 방법도 함께)

## 5. 보고 · 전파 기준
(누구에게, 언제까지, 어떤 양식으로. 야간/휴일 기준 포함)

## 6. 후속 확인
(조치 뒤 무엇을 언제 다시 보는가)

## 7. 관련 문서
(연관 절차 · 관계사 요구사항 · 장비 매뉴얼)
"""


# --------------------------------------------------------------------------- 열람 판정

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


def get_or_404(db: Session, actor: User, article_id: int, *,
               include_deleted: bool = False) -> KnowledgeArticle:
    stmt = select(KnowledgeArticle).where(KnowledgeArticle.id == article_id,
                                          visible_clause(actor))
    if not include_deleted:
        stmt = stmt.where(KnowledgeArticle.is_deleted == false())
    row = db.scalar(stmt)
    if row is None:
        raise NotFound("운영 지식을 찾을 수 없습니다.")
    return row


def can_edit(actor: User, row: KnowledgeArticle) -> bool:
    """고치는 권한은 작성자와 근무 관리자에게만. 읽는 범위와 따로 둔다(§4)."""
    return row.created_by == actor.id or actor.role_code in MANAGERS


# --------------------------------------------------------------------------- 범위 · 태그

def _scope(db: Session, row: KnowledgeArticle, actor: User, visibility: str,
           group_ids: list[int]) -> None:
    wanted = {int(v) for v in group_ids}
    if visibility == VIS_GROUPS and not wanted:
        raise ValidationFailed("그룹을 제한하려면 공개할 그룹을 하나 이상 선택하십시오.",
                               detail={"field": "group_ids"})
    if visibility == VIS_ALL:
        row.visibility = VIS_ALL
        row.group_links.clear()
        db.flush()
        return
    if visibility != VIS_GROUPS:
        raise ValidationFailed("운영 지식 공개 범위 값이 잘못됐습니다.",
                               detail={"field": "visibility"})
    permitted = set(group_service.my_group_ids(db, actor.id))
    if not wanted <= permitted:
        raise ValidationFailed("내가 속하지 않은 그룹에는 운영 지식을 공개할 수 없습니다.",
                               detail={"field": "group_ids"})
    active = set(db.scalars(select(Group.id).where(
        Group.id.in_(wanted), Group.is_active.is_(True))).all())
    if active != wanted:
        raise ValidationFailed("사용 중지된 그룹에는 공개할 수 없습니다.",
                               detail={"field": "group_ids"})
    existing = {link.group_id: link for link in row.group_links}
    for gid, link in existing.items():
        if gid not in wanted:
            row.group_links.remove(link)
    for gid in sorted(wanted - set(existing)):
        row.group_links.append(KnowledgeGroup(group_id=gid))
    row.visibility = VIS_GROUPS
    db.flush()


def _clean_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in tags or []:
        tag = (raw or "").strip().lstrip("#")
        if tag and tag not in out and len(tag) <= 40:
            out.append(tag)
    if len(out) > 20:
        raise ValidationFailed("태그는 20개까지 붙일 수 있습니다.", detail={"field": "tags"})
    return out


def _apply_tags(db: Session, row: KnowledgeArticle, tags: list[str]) -> None:
    wanted = set(tags)
    existing = {link.tag: link for link in row.tag_links}
    for tag, link in existing.items():
        if tag not in wanted:
            row.tag_links.remove(link)
    for tag in tags:
        if tag not in existing:
            row.tag_links.append(KnowledgeTag(tag=tag))
    db.flush()


def tags_of(row: KnowledgeArticle) -> list[str]:
    return sorted(x.tag for x in row.tag_links)


# --------------------------------------------------------------------------- 개정 이력

def _snapshot(db: Session, row: KnowledgeArticle, actor: User,
              change_note: str | None) -> None:
    """현재 내용을 그 판 번호로 한 줄 남긴다. 같은 번호가 이미 있으면 덮지 않는다."""
    already = db.scalar(select(KnowledgeRevision.id).where(
        KnowledgeRevision.article_id == row.id,
        KnowledgeRevision.version_no == row.version_no))
    if already is not None:
        return
    db.add(KnowledgeRevision(
        article_id=row.id, version_no=row.version_no, category=row.category,
        title=row.title, body=row.body, visibility=row.visibility,
        tags=", ".join(tags_of(row)), change_note=(change_note or None),
        changed_by=actor.id, changed_at=now()))
    db.flush()


def revisions(db: Session, actor: User, article_id: int) -> list[dict[str, Any]]:
    row = get_or_404(db, actor, article_id, include_deleted=True)
    rows = db.execute(
        select(KnowledgeRevision, User.display_name)
        .join(User, User.id == KnowledgeRevision.changed_by, isouter=True)
        .where(KnowledgeRevision.article_id == row.id)
        .order_by(KnowledgeRevision.version_no.desc())
    ).all()
    return [{"version_no": rev.version_no, "title": rev.title, "category": rev.category,
             "visibility": rev.visibility, "tags": rev.tags, "change_note": rev.change_note,
             "changed_by": rev.changed_by, "changed_by_name": name,
             "changed_at": rev.changed_at, "body_chars": len(rev.body or "")}
            for rev, name in rows]


def revision_body(db: Session, actor: User, article_id: int, version_no: int) -> dict[str, Any]:
    """한 판의 본문. 두 판을 받아 화면에서 나란히 비교한다."""
    row = get_or_404(db, actor, article_id, include_deleted=True)
    rev = db.scalar(select(KnowledgeRevision).where(
        KnowledgeRevision.article_id == row.id, KnowledgeRevision.version_no == version_no))
    if rev is None:
        raise NotFound("해당 판의 이력이 없습니다.")
    return {"version_no": rev.version_no, "title": rev.title, "category": rev.category,
            "body": rev.body, "tags": rev.tags, "visibility": rev.visibility,
            "change_note": rev.change_note, "changed_at": rev.changed_at}


def restore_revision(db: Session, actor: User, article_id: int, version_no: int,
                     ctx: RequestContext | None = None) -> KnowledgeArticle:
    """옛 판의 내용을 되살린다. 지우지 않고 **새 판**으로 올려 이력이 끊기지 않게 한다."""
    row = get_or_404(db, actor, article_id, include_deleted=True)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 복원할 수 있습니다.")
    rev = db.scalar(select(KnowledgeRevision).where(
        KnowledgeRevision.article_id == row.id, KnowledgeRevision.version_no == version_no))
    if rev is None:
        raise NotFound("해당 판의 이력이 없습니다.")
    _snapshot(db, row, actor, "복원 전 상태")
    row.title = rev.title
    row.body = rev.body
    row.category = rev.category
    row.version_no = row.version_no + 1
    row.updated_by = actor.id
    _apply_tags(db, row, _clean_tags([t for t in (rev.tags or "").split(",")]))
    db.flush()
    _snapshot(db, row, actor, f"{version_no}판 복원")
    record(db, action=actions.KNOWLEDGE_UPDATE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id,
           after={"restored_from": version_no, "version_no": row.version_no,
                  "title": row.title})
    return row


# --------------------------------------------------------------------------- 인수인계 연계

def links_of(db: Session, actor: User, article_id: int) -> list[dict[str, Any]]:
    """연결된 인수인계 — **읽는 사람이 볼 수 있는 것만**. 연결이 권한을 넓히지 않는다."""
    rows = db.execute(
        select(Handover.id, Handover.title, Handover.status_code, Handover.created_at)
        .join(KnowledgeHandoverLink, KnowledgeHandoverLink.handover_id == Handover.id)
        .where(KnowledgeHandoverLink.article_id == article_id,
               Handover.is_deleted == false(),
               group_service.visible_clause(db, actor.id))
        .order_by(Handover.created_at.desc())
    ).all()
    return [{"handover_id": i, "title": t, "status_code": s, "created_at": c}
            for i, t, s, c in rows]


def link_handover(db: Session, actor: User, article_id: int, handover_id: int,
                  ctx: RequestContext | None = None) -> dict[str, Any]:
    """문서에 인수인계를 건다. 내가 볼 수 없는 인수인계는 걸 수 없다."""
    row = get_or_404(db, actor, article_id)
    handover = db.scalar(select(Handover).where(
        Handover.id == handover_id, Handover.is_deleted == false(),
        group_service.visible_clause(db, actor.id)))
    if handover is None:
        raise NotFound("인수인계를 찾을 수 없습니다.")
    already = db.scalar(select(KnowledgeHandoverLink.id).where(
        KnowledgeHandoverLink.article_id == row.id,
        KnowledgeHandoverLink.handover_id == handover.id))
    if already is None:
        db.add(KnowledgeHandoverLink(article_id=row.id, handover_id=handover.id,
                                     created_by=actor.id))
        db.flush()
        record(db, action=actions.KNOWLEDGE_LINK, ctx=ctx, user=actor,
               resource_type="KNOWLEDGE", resource_id=row.id,
               after={"handover_id": handover.id, "title": handover.title})
    return {"handover_id": handover.id, "title": handover.title,
            "status_code": handover.status_code, "created_at": handover.created_at}


def unlink_handover(db: Session, actor: User, article_id: int, handover_id: int,
                    ctx: RequestContext | None = None) -> None:
    row = get_or_404(db, actor, article_id)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 연결을 끊을 수 있습니다.")
    db.execute(delete(KnowledgeHandoverLink).where(
        KnowledgeHandoverLink.article_id == row.id,
        KnowledgeHandoverLink.handover_id == handover_id))
    db.flush()
    record(db, action=actions.KNOWLEDGE_LINK, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id,
           after={"unlinked_handover_id": handover_id})


def articles_for_handover(db: Session, actor: User, handover_id: int) -> list[dict[str, Any]]:
    """인수인계 화면에서 '관련 절차 열기' — 걸어 둔 문서를 보여 준다."""
    rows = db.scalars(
        select(KnowledgeArticle)
        .join(KnowledgeHandoverLink,
              KnowledgeHandoverLink.article_id == KnowledgeArticle.id)
        .where(KnowledgeHandoverLink.handover_id == handover_id,
               KnowledgeArticle.is_deleted == false(), visible_clause(actor))
        .order_by(KnowledgeArticle.is_pinned.desc(), KnowledgeArticle.updated_at.desc())
    ).all()
    return [{"id": x.id, "title": x.title, "category": x.category} for x in rows]


#: 추천에서 걸러낼 너무 흔한 말. 이 말로는 어떤 문서든 걸린다.
_STOPWORDS = frozenset({"관제", "확인", "요청", "문의", "건", "관련", "내용", "조치", "장애",
                        "오류", "에러", "발생", "처리", "완료", "진행", "대응", "보고"})


def suggest_for_text(db: Session, actor: User, text: str, *,
                     limit: int = 5) -> list[dict[str, Any]]:
    """제목에 쓰인 말로 관련 절차를 찾아 준다 — 규칙 기반이다(AI 를 쓰지 않는다).

    인계 제목에서 두 글자 이상인 낱말을 뽑아 제목 · 태그에 걸리는 문서를 센다.
    맞히지 못해도 손해가 없고, 틀린 추천이 열람 권한을 넓히지도 않는다.
    """
    import re

    words = [w for w in re.split(r"[^0-9A-Za-z가-힣]+", text or "")
             if len(w) >= 2 and w not in _STOPWORDS][:12]
    if not words:
        return []
    hits = db.execute(
        select(KnowledgeArticle.id, KnowledgeArticle.title, KnowledgeArticle.category,
               func.count().label("score"))
        .join(KnowledgeTag, KnowledgeTag.article_id == KnowledgeArticle.id, isouter=True)
        .where(KnowledgeArticle.is_deleted == false(), visible_clause(actor),
               or_(*[KnowledgeArticle.title.icontains(w, autoescape=True) for w in words],
                   *[KnowledgeTag.tag.icontains(w, autoescape=True) for w in words]))
        .group_by(KnowledgeArticle.id, KnowledgeArticle.title, KnowledgeArticle.category)
        .order_by(func.count().desc(), KnowledgeArticle.updated_at.desc())
        .limit(limit)
    ).all()
    return [{"id": i, "title": t, "category": c, "score": int(s)} for i, t, c, s in hits]


# --------------------------------------------------------------------------- 조회 · 쓰기

def to_out(db: Session, actor: User, row: KnowledgeArticle) -> dict[str, Any]:
    names = dict(db.execute(
        select(User.id, User.display_name)
        .where(User.id.in_({x for x in (row.created_by, row.updated_by) if x}))
    ).all())
    overdue = bool(row.review_due and row.review_due < date.today())
    return {
        "id": row.id, "category": row.category, "title": row.title, "body": row.body,
        "visibility": row.visibility, "group_ids": sorted(x.group_id for x in row.group_links),
        "group_names": sorted(db.scalars(select(Group.name).where(
            Group.id.in_([x.group_id for x in row.group_links]))).all())
        if row.group_links else [],
        "tags": tags_of(row),
        "is_pinned": row.is_pinned, "review_due": row.review_due,
        "review_overdue": overdue,
        "version_no": row.version_no,
        "created_by": row.created_by, "created_by_name": names.get(row.created_by),
        "updated_by": row.updated_by, "updated_by_name": names.get(row.updated_by),
        "created_at": row.created_at, "updated_at": row.updated_at,
        "is_deleted": row.is_deleted,
        "can_edit": can_edit(actor, row),
    }


def list_for(db: Session, actor: User, q: str | None = None, category: str | None = None,
             tag: str | None = None, review_due_only: bool = False,
             include_deleted: bool = False,
             offset: int = 0, limit: int = 50) -> list[KnowledgeArticle]:
    stmt = select(KnowledgeArticle).where(visible_clause(actor))
    if not include_deleted:
        stmt = stmt.where(KnowledgeArticle.is_deleted == false())
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(or_(
            KnowledgeArticle.title.icontains(term, autoescape=True),
            KnowledgeArticle.body.icontains(term, autoescape=True),
            exists(select(KnowledgeTag.id).where(
                KnowledgeTag.article_id == KnowledgeArticle.id,
                KnowledgeTag.tag.icontains(term, autoescape=True)).correlate(KnowledgeArticle)),
        ))
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    if tag and tag.strip():
        stmt = stmt.where(exists(select(KnowledgeTag.id).where(
            KnowledgeTag.article_id == KnowledgeArticle.id,
            KnowledgeTag.tag == tag.strip()).correlate(KnowledgeArticle)))
    if review_due_only:
        stmt = stmt.where(KnowledgeArticle.review_due.is_not(None),
                          KnowledgeArticle.review_due <= date.today())
    return list(db.scalars(stmt.order_by(KnowledgeArticle.is_pinned.desc(),
                                         KnowledgeArticle.updated_at.desc(),
                                         KnowledgeArticle.id.desc())
                           .offset(offset).limit(limit)))


def create(db: Session, actor: User, data: dict[str, Any],
           ctx: RequestContext | None = None) -> KnowledgeArticle:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationFailed("제목을 입력하십시오.", detail={"field": "title"})
    row = KnowledgeArticle(
        title=title, category=data["category"], body=data.get("body") or "",
        is_pinned=bool(data.get("is_pinned")), review_due=data.get("review_due"),
        created_by=actor.id, updated_by=actor.id, version_no=1,
    )
    db.add(row)
    db.flush()
    _apply_tags(db, row, _clean_tags(data.get("tags")))
    _scope(db, row, actor, data.get("visibility") or VIS_ALL, data.get("group_ids") or [])
    _snapshot(db, row, actor, data.get("change_note") or "최초 등록")
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
    note = changes.pop("change_note", None)
    title = (changes.get("title") if changes.get("title") is not None else row.title).strip()
    if not title:
        raise ValidationFailed("제목을 입력하십시오.", detail={"field": "title"})
    visibility = changes.get("visibility") or row.visibility
    gids = changes.get("group_ids")
    if gids is None:
        gids = [x.group_id for x in row.group_links]
    tags = _clean_tags(changes["tags"]) if changes.get("tags") is not None else None

    # 바꾸기 전 모습을 먼저 남긴다 — 남기기 전에 덮어쓰면 비교할 대상이 사라진다.
    _snapshot(db, row, actor, None)

    # 판 번호 비교와 갱신을 한 SQL 문으로 처리해 동시 편집 덮어쓰기를 막는다.
    vals = {k: v for k, v in changes.items()
            if k in ("category", "body", "is_pinned", "review_due")
            and (v is not None or k == "review_due")}
    vals.update(title=title, updated_by=actor.id, version_no=expected + 1)
    result = db.execute(update(KnowledgeArticle).where(
        KnowledgeArticle.id == article_id, KnowledgeArticle.version_no == expected
    ).values(**vals).execution_options(synchronize_session="fetch"))
    if result.rowcount != 1:
        raise VersionConflict("다른 사람이 수정했습니다. 다시 불러온 뒤 수정하십시오.")
    db.refresh(row)
    if tags is not None:
        _apply_tags(db, row, tags)
    _scope(db, row, actor, visibility, gids)
    _snapshot(db, row, actor, note)
    record(db, action=actions.KNOWLEDGE_UPDATE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id,
           after={"version_no": row.version_no, "title": row.title, "visibility": row.visibility,
                  "group_ids": [x.group_id for x in row.group_links]})
    return row


def delete_article(db: Session, actor: User, article_id: int,
                   ctx: RequestContext | None = None) -> None:
    """지운 표시만 한다. 절차 문서는 사고 조사에서 다시 필요할 수 있어 지우지 않는다."""
    row = get_or_404(db, actor, article_id)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 삭제할 수 있습니다.")
    row.is_deleted = True
    row.updated_by = actor.id
    db.flush()
    record(db, action=actions.KNOWLEDGE_DELETE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id, before={"title": row.title})


def restore_article(db: Session, actor: User, article_id: int,
                    ctx: RequestContext | None = None) -> KnowledgeArticle:
    row = get_or_404(db, actor, article_id, include_deleted=True)
    if not can_edit(actor, row):
        raise Forbidden("작성자 또는 근무 관리자만 복원할 수 있습니다.")
    if not row.is_deleted:
        return row
    row.is_deleted = False
    row.updated_by = actor.id
    db.flush()
    record(db, action=actions.KNOWLEDGE_RESTORE, ctx=ctx, user=actor,
           resource_type="KNOWLEDGE", resource_id=row.id, after={"title": row.title})
    return row


# 기존 호출 이름 유지(1.3.1 초기 구현이 delete 로 불렀다).
delete = delete_article
