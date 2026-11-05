"""Export 라우터. 목록과 같은 DSL 을 받아 파일을 만들고, 내려받기 토큰을 준다."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.models.user import User
from app.schemas.importjob import ExportOut, ExportRequest
from app.services import export_service

router = APIRouter(prefix="/export", tags=["export"],
                   dependencies=[Depends(require_password_changed)])

_MEDIA = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv; charset=utf-8",
}


@router.get("/columns")
def columns(_: User = Depends(require("export:run"))):
    return [{"key": k, "label": v[0], "default": k in export_service.DEFAULT_COLUMNS}
            for k, v in export_service.COLUMNS.items()]


@router.post("/handovers", response_model=ExportOut)
def export_handovers(payload: ExportRequest, db: Session = Depends(get_db),
                     actor: User = Depends(require("export:run")),
                     ctx: RequestContext = Depends(get_context)):
    return export_service.export(db, payload, actor, ctx)


@router.get("/download/{token}")
def download(token: str, db: Session = Depends(get_db),
             actor: User = Depends(require("export:run"))):
    path, name = export_service.resolve_download(token, actor, db)
    return FileResponse(path, filename=name, media_type=_MEDIA.get(path.suffix, "application/octet-stream"))
