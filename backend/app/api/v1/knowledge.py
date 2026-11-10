"""운영 지식 API.

목록 · 상세 · 첨부 · 개정 이력 모두 같은 열람 판정(knowledge_service.visible_clause)을
지난다. 문서 번호를 알아도 볼 수 없는 문서는 404 다(있다는 사실도 알려 주지 않는다).
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.knowledge import (ArticleCreate, ArticleOut, ArticleUpdate, LinkCreate,
                                   LinkOut, RevisionBody, RevisionOut, SuggestOut)
from app.services import knowledge_service as svc

router = APIRouter(prefix="/knowledge", tags=["knowledge"],
                   dependencies=[Depends(require_password_changed)])


@router.get("/categories")
def categories(_: User = Depends(require("handover:read"))):
    return list(svc.CATEGORIES)


@router.get("/template")
def template(_: User = Depends(require("handover:read"))):
    """새 문서의 표준 양식(목적·범위 / 탐지·확인 / 분석 / 조치 / 보고 / 후속 / 관련 문서)."""
    return {"body": svc.TEMPLATE}


@router.get("", response_model=list[ArticleOut])
def list_articles(q: str | None = Query(default=None, max_length=100),
                  category: str | None = Query(default=None, max_length=50),
                  tag: str | None = Query(default=None, max_length=40),
                  review_due_only: bool = Query(default=False),
                  include_deleted: bool = Query(default=False),
                  offset: int = Query(default=0, ge=0),
                  limit: int = Query(default=50, ge=1, le=100),
                  db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    rows = svc.list_for(db, actor, q=q, category=category, tag=tag,
                        review_due_only=review_due_only, include_deleted=include_deleted,
                        offset=offset, limit=limit)
    return [svc.to_out(db, actor, x) for x in rows]


@router.get("/suggest", response_model=list[SuggestOut])
def suggest(text: str = Query(default="", max_length=300),
            handover_id: int | None = Query(default=None),
            db: Session = Depends(get_db),
            actor: User = Depends(require("handover:read"))):
    """제목·본문의 낱말로 관련 절차를 추천한다(규칙 기반, AI 아님)."""
    if handover_id is not None:
        from sqlalchemy import false, select

        from app.models.handover import Handover
        from app.services import group_service
        row = db.scalar(select(Handover).where(
            Handover.id == handover_id, Handover.is_deleted == false(),
            group_service.visible_clause(db, actor.id)))
        if row is not None:
            text = f"{row.title} {text}"
    return svc.suggest_for_text(db, actor, text)


@router.get("/for-handover/{handover_id}", response_model=list[SuggestOut])
def for_handover(handover_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:read"))):
    """인수인계에 걸어 둔 절차 문서."""
    return svc.articles_for_handover(db, actor, handover_id)


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
def create_article(payload: ArticleCreate, db: Session = Depends(get_db),
                   actor: User = Depends(require("handover:create")),
                   ctx: RequestContext = Depends(get_context)):
    return svc.to_out(db, actor, svc.create(db, actor, payload.model_dump(), ctx))


@router.get("/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:read"))):
    return svc.to_out(db, actor, svc.get_or_404(db, actor, article_id, include_deleted=True))


@router.patch("/{article_id}", response_model=ArticleOut)
def edit_article(article_id: int, payload: ArticleUpdate, db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:update_own")),
                 ctx: RequestContext = Depends(get_context)):
    return svc.to_out(db, actor, svc.edit(db, actor, article_id,
                      payload.model_dump(exclude_unset=True), ctx))


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article(article_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("handover:update_own")),
                   ctx: RequestContext = Depends(get_context)):
    svc.delete_article(db, actor, article_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{article_id}/restore", response_model=ArticleOut)
def restore_article(article_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:update_own")),
                    ctx: RequestContext = Depends(get_context)):
    return svc.to_out(db, actor, svc.restore_article(db, actor, article_id, ctx))


# --------------------------------------------------------------------------- 개정 이력

@router.get("/{article_id}/revisions", response_model=list[RevisionOut])
def revisions(article_id: int, db: Session = Depends(get_db),
              actor: User = Depends(require("handover:read"))):
    return svc.revisions(db, actor, article_id)


@router.get("/{article_id}/revisions/{version_no}", response_model=RevisionBody)
def revision_body(article_id: int, version_no: int, db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    """한 판의 본문 — 두 번 불러 화면에서 나란히 비교한다."""
    return svc.revision_body(db, actor, article_id, version_no)


@router.post("/{article_id}/revisions/{version_no}/restore", response_model=ArticleOut)
def restore_revision(article_id: int, version_no: int, db: Session = Depends(get_db),
                     actor: User = Depends(require("handover:update_own")),
                     ctx: RequestContext = Depends(get_context)):
    return svc.to_out(db, actor,
                      svc.restore_revision(db, actor, article_id, version_no, ctx))


# --------------------------------------------------------------------------- 인수인계 연계

@router.get("/{article_id}/handovers", response_model=list[LinkOut])
def links(article_id: int, db: Session = Depends(get_db),
          actor: User = Depends(require("handover:read"))):
    svc.get_or_404(db, actor, article_id, include_deleted=True)
    return svc.links_of(db, actor, article_id)


@router.post("/{article_id}/handovers", response_model=LinkOut,
             status_code=status.HTTP_201_CREATED)
def add_link(article_id: int, payload: LinkCreate, db: Session = Depends(get_db),
             actor: User = Depends(require("handover:read")),
             ctx: RequestContext = Depends(get_context)):
    return svc.link_handover(db, actor, article_id, payload.handover_id, ctx)


@router.delete("/{article_id}/handovers/{handover_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def remove_link(article_id: int, handover_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:update_own")),
                ctx: RequestContext = Depends(get_context)):
    svc.unlink_handover(db, actor, article_id, handover_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
