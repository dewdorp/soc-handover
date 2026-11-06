"""운영 지식 API — 목록 및 상세는 그룹 공개 범위로 필터한다."""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.knowledge import ArticleCreate, ArticleOut, ArticleUpdate
from app.services import knowledge_service as svc

router = APIRouter(prefix="/knowledge", tags=["knowledge"],
                   dependencies=[Depends(require_password_changed)])


@router.get("/categories")
def categories(_: User = Depends(require("handover:read"))):
    return list(svc.CATEGORIES)


@router.get("", response_model=list[ArticleOut])
def list_articles(q: str | None = Query(default=None, max_length=100),
                  category: str | None = Query(default=None, max_length=50),
                  offset: int = Query(default=0, ge=0),
                  limit: int = Query(default=50, ge=1, le=100),
                  db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    return [svc.to_out(db, actor, x)
            for x in svc.list_for(db, actor, q=q, category=category, offset=offset, limit=limit)]


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
def create_article(payload: ArticleCreate, db: Session = Depends(get_db),
                   actor: User = Depends(require("handover:create")),
                   ctx: RequestContext = Depends(get_context)):
    return svc.to_out(db, actor, svc.create(db, actor, payload.model_dump(), ctx))


@router.get("/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:read"))):
    return svc.to_out(db, actor, svc.get_or_404(db, actor, article_id))


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
    svc.delete(db, actor, article_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
