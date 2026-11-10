"""장비 비밀번호 보관 라우터 (API.md §11). 규칙은 services/credential_service.py 에 있다.

비밀번호 값이 나가는 경로는 `/reveal` 둘뿐이고, 둘 다 본인 확인과 감사 기록을 거친다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.credential import (CredentialCreate, CredentialOut, CredentialUpdate,
                                    CredentialVersionOut, RevealOut, RevealRequest)
from app.services import credential_service as svc
from app.services import vault_session_service as vault
from app.audit import actions
from app.audit.recorder import record
from app.core import crypto

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


@router.post("/vault/unlock")
def unlock_vault(payload: RevealRequest, response: Response,
                 db: Session = Depends(get_db), actor: User = Depends(require("credential:read")),
                 ctx: RequestContext = Depends(get_context)):
    """본인 인증 한 번으로 제한 시간 내 허용된 현재 비밀번호를 함께 본다."""
    response.headers["Cache-Control"] = "no-store"
    return vault.unlock(db, actor, payload.password, ctx)


@router.get("/vault/status")
def vault_status(response: Response,
                 x_vault_token: str = Header(default="", max_length=128),
                 actor: User = Depends(require("credential:read")),
                 ctx: RequestContext = Depends(get_context)):
    response.headers["Cache-Control"] = "no-store"
    return vault.status(actor, x_vault_token, ctx)


@router.post("/vault/extend")
def extend_vault(response: Response,
                 x_vault_token: str = Header(default="", max_length=128),
                 db: Session = Depends(get_db),
                 actor: User = Depends(require("credential:read")),
                 ctx: RequestContext = Depends(get_context)):
    response.headers["Cache-Control"] = "no-store"
    return vault.extend(db, actor, x_vault_token, ctx)


@router.post("/vault/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock_vault(x_vault_token: str = Header(default="", max_length=128),
               db: Session = Depends(get_db), actor: User = Depends(require("credential:read")),
               ctx: RequestContext = Depends(get_context)):
    vault.lock(actor, x_vault_token, ctx, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/vault/secrets", response_model=list[RevealOut])
def vault_secrets(response: Response, ids: list[int] = Query(default=[]),
                  x_vault_token: str = Header(default="", max_length=128),
                  db: Session = Depends(get_db), actor: User = Depends(require("credential:read")),
                  ctx: RequestContext = Depends(get_context)):
    """현재 목록의 선택한 항목만 일괄 복호화. 개인 범위는 작성자에게만 공개."""
    vault.status(actor, x_vault_token, ctx)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    if len(ids) > 200 or len(set(ids)) != len(ids):
        from app.core.errors import ValidationFailed
        raise ValidationFailed("한 번에 최대 200개까지 열 수 있습니다.")
    rows = [svc.get_or_404(db, actor, rid) for rid in ids]
    out = [
        {"credential_id": row.id, "version_no": row.current_version_no,
         "secret": crypto.decrypt(row.secret_cipher, aad=f"credential:{row.id}"),
         "device_name": row.device_name, "username": row.username}
        for row in rows
    ]
    record(db, action=actions.CREDENTIAL_VAULT_BATCH_REVEAL, ctx=ctx, user=actor,
           resource_type="CREDENTIAL",
           detail={"count": len(out), "credential_ids": [r.id for r in rows]})
    return out


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
