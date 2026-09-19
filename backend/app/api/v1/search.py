"""검색 라우터 — DSL 검색 · Facet · 레지스트리 조회 · 통합 검색.

계층 순서(ARCHITECTURE.md §5.1)는 ① Column Filter → ② Quick → ③ Global → ④ SavedView
→ ⑤ Advanced → ⑥ FTS → ⑦ AI 다. 여기까지가 ①~⑥ 이고, AI 는 나중에 이 위에 얇게 얹힌다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.auth.rbac import has_permission
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
    """Ctrl+K 팔레트 · 통합검색 화면. 종류별 상위 N + 총 건수.

    인수인계는 목록 검색창과 같은 규칙(제목·내용·비고·관계사·인명·태그)으로 찾고,
    결과마다 **어느 칸에서 걸렸는지(matched)** 를 붙인다 — 확인자 이름으로만 걸린 건은
    제목·내용만 봐서는 왜 나왔는지 알 수 없다. Attachment 는 해당 Phase 에서 덧붙인다.
    """
    hits: list[GlobalHit] = []
    totals: dict[str, int] = {}
    term = payload.q.strip()

    if "handover" in payload.scope:
        from app.repositories import handover_repo
        from app.search.compiler import CompileContext

        request = SearchRequest(q=payload.q, size=payload.limit, page=1)
        dsl.validate(request, permissions=frozenset())
        ctx = CompileContext(user_id=actor.id)
        totals["handover"] = handover_repo.count(db, request, ctx, include_deleted=False)
        for h in handover_repo.search(db, request, ctx, include_deleted=False):
            matched = _handover_matches(h, term)
            hits.append(GlobalHit(
                type="handover", id=h.id, title=h.title, matched=[m for m, _ in matched],
                snippet=_best_snippet(matched, h.content, payload.q),
                company=h.company.name if h.company else None, date=h.registered_date))

    if "task" in payload.scope and has_permission(actor.role_code, "task:read"):
        from app.schemas.task import TaskSearchRequest
        from app.services import task_service

        tasks, totals["task"] = task_service.search(db, actor, TaskSearchRequest(
            q=payload.q, include_closed=True, sort="updated_at", size=payload.limit))
        for t in tasks:
            matched = _text_matches([("제목", t.title), ("내용", t.description)], term)
            hits.append(GlobalHit(
                type="task", id=t.id, title=t.title, matched=[m for m, _ in matched],
                snippet=_best_snippet(matched, t.description, payload.q),
                company=t.company.name if t.company else None, date=t.due_date))

    if "schedule" in payload.scope and has_permission(actor.role_code, "schedule:read"):
        from sqlalchemy import func, or_, select

        from app.core.time import KST
        from app.models.schedule import Schedule

        cond = (Schedule.is_deleted.is_(False),
                or_(Schedule.title.icontains(term, autoescape=True),
                    Schedule.description.icontains(term, autoescape=True)))
        totals["schedule"] = db.scalar(select(func.count()).select_from(Schedule).where(*cond)) or 0
        for sched in db.scalars(select(Schedule).where(*cond)
                                .order_by(Schedule.start_at.desc()).limit(payload.limit)):
            matched = _text_matches([("제목", sched.title), ("내용", sched.description)], term)
            hits.append(GlobalHit(
                type="schedule", id=sched.id, title=sched.title, matched=[m for m, _ in matched],
                snippet=_best_snippet(matched, sched.description, payload.q),
                company=sched.company.name if sched.company else None,
                date=sched.start_at.astimezone(KST).date()))

    return GlobalSearchResponse(q=payload.q, hits=hits, totals=totals)


def _person(user, raw: str | None) -> str | None:
    return user.display_name if user is not None else raw


def _text_matches(fields: list[tuple[str, str | None]], term: str) -> list[tuple[str, str]]:
    needle = term.lower()
    return [(label, value) for label, value in fields if value and needle in value.lower()]


def _handover_matches(h, term: str) -> list[tuple[str, str]]:
    from app.services.handover_service import tag_names

    return _text_matches([
        ("제목", h.title), ("내용", h.content), ("비고", h.remark),
        ("관계사", h.company.name if h.company else None),
        ("전달자", _person(h.sender, h.sender_name_raw)),
        ("담당자", _person(h.assignee, h.assignee_name_raw)),
        ("확인자", _person(h.checker, h.checker_name_raw)),
        ("태그", ", ".join(tag_names(h)) or None),
    ], term)


def _best_snippet(matched: list[tuple[str, str]], body: str | None, term: str) -> str | None:
    """본문에서 걸렸으면 그 주변. 제목에서 걸렸으면 본문 앞부분(무슨 건인지).
    사람·관계사·태그에서만 걸렸으면 '확인자: 홍길동' 처럼 — 제목만 봐서는 왜 나왔는지 모르므로."""
    labels = [label for label, _ in matched]
    for label, value in matched:
        if label in ("내용", "비고"):
            return _snippet(value, term)
    if "제목" in labels or not matched:
        return _snippet(body, term)
    label, value = matched[0]
    return f"{label}: {value}"


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
