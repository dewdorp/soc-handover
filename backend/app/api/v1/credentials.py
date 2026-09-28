"""장비 비밀번호 보관 라우터 (API.md §11). 규칙은 services/credential_service.py 에 있다.

비밀번호 값이 나가는 경로는 `/reveal` 둘뿐이고, 둘 다 본인 확인과 감사 기록을 거친다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.credential import (CredentialCreate, CredentialOut, CredentialUpdate,
                                    CredentialVersionOut, RevealOut, RevealRequest)
from app.services import credential_service as svc

router = APIRouter(prefix="/credentials", tags=["credentials"],
                   dependencies=[Depends(require_password_changed)])


@router.get("", response_model=list[CredentialOut])
def list_credentials(scope: str | None = Query(default=None, max_length=10),
                     company_id: int | None = None,
                     q: str | None = Query(default=None, max_length=100),
                     db: Session = Depends(get_db),
                     actor: User = Depends(require("credential:read"))):
    """공용 전부 + 내 개인 것. 남의 개인 항목은 여기에 나오지 않는다."""
    return [svc.to_out(db, actor, row) for row in
            svc.list_for(db, actor, scope=scope, company_id=company_id, q=q)]


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(payload: CredentialCreate, db: Session = Depends(get_db),
                      actor: User = Depends(require("credential:create")),
                      ctx: RequestContext = Depends(get_context)):
    row = svc.create(db, actor, payload.model_dump(), ctx)
    return svc.to_out(db, actor, row)


@router.get("/{credential_id}", response_model=CredentialOut)
def get_credential(credential_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("credential:read"))):
    return svc.to_out(db, actor, svc.get_or_404(db, actor, credential_id))


@router.patch("/{credential_id}", response_model=CredentialOut)
def update_credential(credential_id: int, payload: CredentialUpdate,
                      db: Session = Depends(get_db),
                      actor: User = Depends(require("credential:update_own")),
                      ctx: RequestContext = Depends(get_context)):
    row = svc.update(db, actor, credential_id, payload.model_dump(exclude_unset=True), ctx)
    return svc.to_out(db, actor, row)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(require("credential:update_own")),
                      ctx: RequestContext = Depends(get_context)):
    svc.delete(db, actor, credential_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{credential_id}/reveal", response_model=RevealOut)
def reveal_credential(credential_id: int, payload: RevealRequest, db: Session = Depends(get_db),
                      actor: User = Depends(require("credential:read")),
                      ctx: RequestContext = Depends(get_context)):
    """지금 비밀번호를 본다 — 본인 확인 뒤, 한 건씩 감사에 남긴다."""
    return svc.reveal(db, actor, credential_id, payload.password, ctx=ctx)


@router.get("/{credential_id}/versions", response_model=list[CredentialVersionOut])
def credential_history(credential_id: int, db: Session = Depends(get_db),
                       actor: User = Depends(require("credential:read"))):
    """무엇이 언제 누구에 의해 바뀌었나(값은 들어 있지 않다)."""
    return svc.history(db, actor, credential_id)


@router.post("/{credential_id}/versions/{version_no}/reveal", response_model=RevealOut)
def reveal_old_secret(credential_id: int, version_no: int, payload: RevealRequest,
                      db: Session = Depends(get_db),
                      actor: User = Depends(require("credential:read")),
                      ctx: RequestContext = Depends(get_context)):
    """바꾸기 전 비밀번호를 본다(장비에 새 값이 안 먹었을 때). 지금 값과 똑같이 감사에 남는다."""
    return svc.reveal(db, actor, credential_id, payload.password, version_no=version_no, ctx=ctx)
