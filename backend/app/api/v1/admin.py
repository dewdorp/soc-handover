"""감사 로그 · 설정 변경 · 인수인계 댓글 · 첨부 · 통계 라우터 (Phase 8, FR-I).

규칙은 services/audit_service · settings_service · comment_service · attachment_service · stats_service 에 있다.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.time import today
from app.models.user import User
from app.schemas.admin import (AttachmentOut, AuditPage, AuditSearch, CommentBody,
                               HandoverCommentOut, SettingUpdate)
from app.services import (attachment_service, audit_service, comment_service, settings_service,
                          stats_service)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_password_changed)])


# --------------------------------------------------------------------------- 감사 로그

@router.get("/audit/catalog")
def audit_catalog(db: Session = Depends(get_db), _: User = Depends(require("audit:read_self"))):
    """행위 목록(한국어 이름 · 묶음) · 기록된 대상 종류 — 화면 필터용."""
    return audit_service.catalog(db)


@router.post("/audit/search", response_model=AuditPage)
def audit_search(payload: AuditSearch, db: Session = Depends(get_db),
                 actor: User = Depends(require("audit:read_self"))):
    rows, total = audit_service.search(db, actor, payload)
    return {"items": [audit_service.to_out(r) for r in rows], "total": total,
            "page": payload.page, "size": payload.size}


@router.post("/audit/export")
def audit_export(payload: AuditSearch, db: Session = Depends(get_db),
                 actor: User = Depends(require("audit:read_self")),
                 ctx: RequestContext = Depends(get_context)):
    """조회 조건 그대로 xlsx. 내려받기는 /exports/{token} (요청자 본인 · 유효시간)."""
    return audit_service.export(db, actor, payload, ctx)


# --------------------------------------------------------------------------- 설정

@router.patch("/settings/{key}")
def update_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db),
                   actor: User = Depends(require("settings:manage")),
                   ctx: RequestContext = Depends(get_context)):
    value = settings_service.validate(key, payload.value)
    settings_service.set_value(db, key, value, actor=actor, ctx=ctx)
    return {"key": key, "value": value}


# --------------------------------------------------------------------------- 인수인계 댓글

@router.get("/handovers/{handover_id}/comments", response_model=list[HandoverCommentOut])
def list_comments(handover_id: int, db: Session = Depends(get_db),
                  actor: User = Depends(require("handover:read"))):
    return [comment_service.to_out(db, actor, c) for c in comment_service.list_for(db, handover_id)]


@router.post("/handovers/{handover_id}/comments", response_model=HandoverCommentOut,
             status_code=status.HTTP_201_CREATED)
def add_comment(handover_id: int, payload: CommentBody, db: Session = Depends(get_db),
                actor: User = Depends(require("handover:comment")),
                ctx: RequestContext = Depends(get_context)):
    return comment_service.to_out(db, actor, comment_service.create(db, actor, handover_id, payload.body, ctx))


@router.patch("/handover-comments/{comment_id}", response_model=HandoverCommentOut)
def edit_comment(comment_id: int, payload: CommentBody, db: Session = Depends(get_db),
                 actor: User = Depends(require("handover:comment")),
                 ctx: RequestContext = Depends(get_context)):
    return comment_service.to_out(db, actor, comment_service.update(db, actor, comment_id, payload.body, ctx))


@router.delete("/handover-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("handover:comment")),
                   ctx: RequestContext = Depends(get_context)):
    comment_service.delete(db, actor, comment_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- 첨부

@router.get("/attachments", response_model=list[AttachmentOut])
def list_attachments(entity_type: str = Query(max_length=20), entity_id: int = Query(ge=1),
                     db: Session = Depends(get_db), actor: User = Depends(require("handover:read"))):
    return [attachment_service.to_out(db, actor, a)
            for a in attachment_service.list_for(db, entity_type, entity_id)]


@router.post("/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
def upload_attachment(entity_type: str = Form(max_length=20), entity_id: int = Form(ge=1),
                      file: UploadFile = File(...), db: Session = Depends(get_db),
                      actor: User = Depends(require("handover:read")),
                      ctx: RequestContext = Depends(get_context)):
    att = attachment_service.upload(db, actor, entity_type, entity_id, file.filename or "", file.file, ctx)
    return attachment_service.to_out(db, actor, att)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, db: Session = Depends(get_db),
                        actor: User = Depends(require("handover:read")),
                        ctx: RequestContext = Depends(get_context)):
    path, att = attachment_service.download(db, actor, attachment_id, ctx)
    db.commit()                                      # 받기 기록을 파일 전송 전에 남긴다
    # 받은 파일을 브라우저가 열지(실행) 않고 저장하게 — 이름은 RFC 5987 로 한글 그대로
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(att.original_name)}",
               "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
    return FileResponse(path, media_type="application/octet-stream", headers=headers)


@router.get("/attachments/{attachment_id}/preview")
def preview_attachment(attachment_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require("handover:read"))):
    """그림 첨부를 화면에서 바로 보여 준다(내려받기와 달리 감사에 남기지 않는다 — 화면을 여는 것과 같다).

    그림인지는 파일 **내용**으로 판단하고, 아니면 거절한다. 브라우저가 내용을 다른 것으로
    해석하지 않도록(nosniff) 하고, 혹시 모를 경우에 대비해 스스로 아무것도 불러오지
    못하게(CSP) 막는다.
    """
    path, att, mime = attachment_service.preview(db, attachment_id)
    headers = {"Content-Disposition": f"inline; filename*=UTF-8''{quote(att.original_name)}",
               "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
               "Cache-Control": "private, max-age=300"}
    return FileResponse(path, media_type=mime, headers=headers)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(attachment_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(require("handover:read")),
                      ctx: RequestContext = Depends(get_context)):
    attachment_service.delete(db, actor, attachment_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- 통계

@router.get("/stats/summary")
def stats_summary(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require("stats:read_all"))):
    """기본은 최근 30일. 최대 366일."""
    end = end or today()
    start = start or (end - timedelta(days=29))
    return stats_service.summary(db, start, end)
