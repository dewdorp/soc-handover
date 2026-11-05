"""RAG 바닥 공사 라우터 — 사례 데이터 · 접근 계약 · 검증 예시.

모델도 벡터 DB 도 없다. 이 라우터는 **나중에 색인을 만들 쪽이 읽을 것**을 내놓는다.
사례는 목록 · 검색 · Excel 과 같은 함수(search_service.iterate)를 지나므로, 여기로 나가는
자료는 요청한 계정이 화면에서 볼 수 있는 것과 정확히 같다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.db import get_db
from app.models.user import User
from app.search.dsl import SearchRequest
from app.services import rag_service

router = APIRouter(prefix="/rag", tags=["rag"],
                   dependencies=[Depends(require_password_changed)])


@router.get("/contract")
def contract(_: User = Depends(require("handover:read"))):
    """접근 계약 · 사례 문서의 칸 설명 · 색인에 넣지 않는 자료 목록."""
    return rag_service.CONTRACT


@router.get("/verification-examples")
def verification_examples(_: User = Depends(require("handover:read"))):
    """'붙였을 때 이것부터 확인하라' — 질문과 반드시 지켜져야 할 것."""
    return list(rag_service.VERIFICATION_EXAMPLES)


@router.get("/cases")
def cases(limit: int = Query(default=20, ge=1, le=500), db: Session = Depends(get_db),
          actor: User = Depends(require("export:run"))):
    """사례 문서 묶음(내보내기 권한). **내가 볼 수 있는 범위**만 나온다."""
    return rag_service.sample(db, actor, limit=limit)


@router.post("/cases")
def cases_for(payload: SearchRequest, limit: int = Query(default=200, ge=1, le=2000),
              db: Session = Depends(get_db),
              actor: User = Depends(require("export:run"))):
    """목록과 같은 검색 조건으로 사례를 뽑는다(기간·관계사별 색인에 쓴다)."""
    return {"schema_version": rag_service.SCHEMA_VERSION,
            "cases": list(rag_service.iterate_cases(db, actor, payload, limit=limit))}
