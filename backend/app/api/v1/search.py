"""검색 라우터 — DSL 검색 · Facet · 레지스트리 조회 · 통합 검색.

계층 순서(ARCHITECTURE.md §5.1)는 ① Column Filter → ② Quick → ③ Global → ④ SavedView
→ ⑤ Advanced → ⑥ FTS → ⑦ AI 다. 여기까지가 ①~⑥ 이고, AI 는 나중에 이 위에 얇게 얹힌다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.config import settings
from app.core.db import get_db
from app.core.pagination import Page
from app.models.user import User
from app.schemas.handover import HandoverListItem
from app.schemas.search import (FacetRequest, FacetValue, GlobalHit, GlobalSearchRequest,
                                GlobalSearchResponse, SearchCapabilities)
from app.search import dsl, fields as reg, quick
from app.search.backends import get_backend
from app.search.dsl import MAX_FILTERS, SearchRequest
from app.services import search_service

router = APIRouter(tags=["search"], dependencies=[Depends(require_password_changed)])


@router.post("/handovers/search", response_model=Page[HandoverListItem])
def search_handovers(payload: SearchRequest, db: Session = Depends(get_db),
                     actor: User = Depends(require("handover:read"))):
    """목록의 기본 경로. GET /handovers 도 결국 이 실행 경로를 지난다."""
    return search_service.run(db, payload, actor)


@router.post("/search/handovers", response_model=Page[HandoverListItem])
def search_handovers_alias(payload: SearchRequest, db: Session = Depends(get_db),
                           actor: User = Depends(require("handover:read"))):
    """API.md §6 의 별칭. 동일 DSL, 동일 실행."""
    return search_service.run(db, payload, actor)


@router.post("/handovers/facets", response_model=list[FacetValue])
def handover_facets(payload: FacetRequest, db: Session = Depends(get_db),
                    actor: User = Depends(require("handover:read"))):
    """컬럼 헤더 필터의 값 목록 + 건수.

    GET 이 아니라 POST 인 이유: 값 목록은 **현재 적용된 다른 필터를 반영한 건수**여야
    의미가 있는데(§5.4), 그 필터는 DSL 이라 query string 에 온전히 담기지 않는다.
    """
    request = SearchRequest.model_validate(
        payload.model_dump(exclude={"field", "facet_q", "limit"}))
    return search_service.facet(db, request, actor, field=payload.field,
                                q=payload.facet_q, limit=payload.limit)


@router.get("/search/fields", response_model=SearchCapabilities)
def capabilities(_: User = Depends(require("search:use"))):
    """필터 UI 구성 근거. 프론트가 필드·연산자 목록을 따로 들고 있지 않게 한다."""
    return SearchCapabilities(
        fields=[f.to_public() for f in reg.HANDOVER_FIELDS.values()],
        quick_filters=quick.catalog(),
        operators=list(reg.ALL_OPS),
        backend=get_backend().name,
        max_filters=MAX_FILTERS,
        max_page_size=settings.MAX_PAGE_SIZE,
    )


@router.post("/search/global", response_model=GlobalSearchResponse)
def global_search(payload: GlobalSearchRequest, db: Session = Depends(get_db),
                  actor: User = Depends(require("search:use"))):
    """Ctrl+K 팔레트. 타입별 상위 N + 총 건수.

    Task / Schedule / Attachment scope 는 해당 Phase 에서 같은 형식으로 덧붙인다.
    """
    request = SearchRequest(q=payload.q, size=payload.limit, page=1)
    dsl.validate(request, permissions=frozenset())

    from app.search.compiler import CompileContext
    from app.repositories import handover_repo

    ctx = CompileContext(user_id=actor.id)
    total = handover_repo.count(db, request, ctx, include_deleted=False)
    rows = handover_repo.search(db, request, ctx, include_deleted=False)

    hits = [
        GlobalHit(
            type="handover", id=h.id, title=h.title,
            snippet=_snippet(h.content, payload.q),
            company=h.company.name if h.company else None,
            date=h.registered_date,
        ) for h in rows
    ]
    return GlobalSearchResponse(q=payload.q, hits=hits, totals={"handover": total})


def _snippet(text: str | None, term: str, width: int = 80) -> str | None:
    """검색어 주변만 잘라 보여준다. 없으면 앞부분."""
    if not text:
        return None
    lowered, needle = text.lower(), term.lower()
    at = lowered.find(needle)
    if at < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, at - width // 3)
    end = min(len(text), at + len(term) + width // 2)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
