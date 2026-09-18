"""Excel Import 라우터 (API.md §7). 상태 전이 규칙은 services/import_service.py 에 있다.

긴 작업은 202 Accepted 로 즉시 돌려주고, 화면은 GET /import/jobs/{id} 로 진행률을 폴링한다.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.pagination import Page, PageParams
from app.models.user import User
from app.schemas.importjob import (DecisionRequest, ErrorOut, ImportJobOut, MappingRequest,
                                   RowOut, ValueMapRequest, ValueStat)
from app.services import import_service as svc

router = APIRouter(prefix="/import", tags=["import"],
                   dependencies=[Depends(require_password_changed)])

_ACCEPTED = status.HTTP_202_ACCEPTED


@router.get("/targets")
def mapping_targets(_: User = Depends(require("import:run"))):
    """컬럼 매핑 드롭다운 항목(시스템 필드)."""
    return svc.mapping_targets()


@router.get("/jobs", response_model=list[ImportJobOut])
def list_jobs(db: Session = Depends(get_db), _: User = Depends(require("import:run"))):
    return svc.list_jobs(db)


@router.post("/jobs", response_model=ImportJobOut, status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db),
                 actor: User = Depends(require("import:run"))):
    """① 업로드 + ② Sheet 분석 + ③ 매핑 제안까지 한 번에 돌려준다."""
    return await svc.upload(db, file, actor)


@router.get("/jobs/{job_id}", response_model=ImportJobOut)
def get_job(job_id: int, db: Session = Depends(get_db),
            _: User = Depends(require("import:run"))):
    """진행률 폴링."""
    return svc.get_or_404(db, job_id)


@router.get("/jobs/{job_id}/analyze")
def analyze(job_id: int, db: Session = Depends(get_db),
            _: User = Depends(require("import:run"))):
    job = svc.get_or_404(db, job_id)
    return {"sheets": (job.sheet_summary or {}).get("sheets", []),
            "headers": (job.sheet_summary or {}).get("headers", []),
            "warnings": (job.sheet_summary or {}).get("warnings", []),
            "suggested_mapping": job.column_mapping, "options": job.options}


@router.post("/jobs/{job_id}/mapping", response_model=ImportJobOut)
def set_mapping(job_id: int, payload: MappingRequest, db: Session = Depends(get_db),
                _: User = Depends(require("import:run"))):
    job = svc.get_or_404(db, job_id)
    return svc.set_mapping(db, job, sheets=payload.sheets,
                           column_mapping=payload.column_mapping,
                           default_status=payload.default_status,
                           default_year=payload.default_year)


@router.post("/jobs/{job_id}/stage", response_model=ImportJobOut, status_code=_ACCEPTED)
def stage(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db),
          _: User = Depends(require("import:run"))):
    """④ 원본 적재 → ⑤ 검증 → ⑥ 중복 검사를 이어서 돌린다."""
    job = svc.get_or_404(db, job_id)
    svc.start_stage(db, job, bg)
    return job


@router.post("/jobs/{job_id}/validate", response_model=ImportJobOut, status_code=_ACCEPTED)
@router.post("/jobs/{job_id}/dedup", response_model=ImportJobOut, status_code=_ACCEPTED)
def prepare(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db),
            _: User = Depends(require("import:run"))):
    """검증과 중복 판정을 원본을 다시 읽지 않고 다시 돌린다(API.md 의 validate·dedup)."""
    job = svc.get_or_404(db, job_id)
    svc.start_prepare(db, job, bg)
    return job


@router.get("/jobs/{job_id}/values", response_model=list[ValueStat])
def value_stats(job_id: int, field: str = Query(pattern="^(company|status)$"),
                db: Session = Depends(get_db), _: User = Depends(require("import:run"))):
    return svc.value_stats(db, svc.get_or_404(db, job_id), field)


@router.post("/jobs/{job_id}/value-map", response_model=ImportJobOut, status_code=_ACCEPTED)
def set_value_map(job_id: int, payload: ValueMapRequest, bg: BackgroundTasks,
                  db: Session = Depends(get_db), _: User = Depends(require("import:run"))):
    job = svc.get_or_404(db, job_id)
    svc.set_value_map(db, job, payload.field, payload.mapping, bg)
    return job


@router.get("/jobs/{job_id}/rows", response_model=Page[RowOut])
@router.get("/jobs/{job_id}/preview", response_model=Page[RowOut])
def rows(job_id: int, kind: str = Query(default="all",
                                        pattern="^(all|error|warning|duplicate|import|skip|imported)$"),
         sheet: str | None = None, page: int = 1, size: int = 50,
         db: Session = Depends(get_db), _: User = Depends(require("import:run"))):
    params = PageParams(page=page, size=size)
    job = svc.get_or_404(db, job_id)
    items, total, importing = svc.rows_page(db, job, kind=kind, sheet=sheet,
                                            page=params.page, size=params.size)
    out = [RowOut.model_validate(r).model_copy(update={"will_import": r.id in importing})
           for r in items]
    return Page.of(out, params, total)


@router.get("/jobs/{job_id}/duplicates", response_model=Page[RowOut])
def duplicates(job_id: int, page: int = 1, size: int = 50, db: Session = Depends(get_db),
               user: User = Depends(require("import:run"))):
    return rows(job_id, kind="duplicate", sheet=None, page=page, size=size, db=db, _=user)


@router.get("/jobs/{job_id}/errors", response_model=Page[ErrorOut])
def errors(job_id: int, page: int = 1, size: int = 50, db: Session = Depends(get_db),
           _: User = Depends(require("import:run"))):
    params = PageParams(page=page, size=size)
    items, total = svc.errors_page(db, svc.get_or_404(db, job_id), params.page, params.size)
    return Page.of([ErrorOut.model_validate(e) for e in items], params, total)


@router.patch("/jobs/{job_id}/decisions")
def decisions(job_id: int, payload: DecisionRequest, db: Session = Depends(get_db),
              _: User = Depends(require("import:run"))):
    job = svc.get_or_404(db, job_id)
    changed = svc.set_decisions(db, job, payload.row_ids, payload.decision)
    return {"changed": changed, "report": job.report}


@router.post("/jobs/{job_id}/commit", response_model=ImportJobOut, status_code=_ACCEPTED)
def commit(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db),
           actor: User = Depends(require("import:run")),
           ctx: RequestContext = Depends(get_context)):
    """⑦ 실제 반영. 같은 Job 에 두 번 눌러도 한 번만 실행된다(조건부 점유)."""
    job = svc.get_or_404(db, job_id)
    svc.start_commit(db, job, actor, ctx, bg)
    return job


@router.get("/jobs/{job_id}/report")
def report(job_id: int, db: Session = Depends(get_db),
           _: User = Depends(require("import:run"))):
    return svc.report(db, svc.get_or_404(db, job_id))


@router.get("/jobs/{job_id}/errors.xlsx")
def errors_xlsx(job_id: int, db: Session = Depends(get_db),
                _: User = Depends(require("import:run"))):
    job = svc.get_or_404(db, job_id)
    path = svc.errors_workbook(db, job)
    return FileResponse(path, filename=f"{job.job_code}_실패행.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument."
                                   "spreadsheetml.sheet")


@router.post("/jobs/{job_id}/rollback", response_model=ImportJobOut, status_code=_ACCEPTED)
def rollback(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db),
             actor: User = Depends(require("import:rollback")),
             ctx: RequestContext = Depends(get_context)):
    """job 단위 되돌리기(Soft Delete). Import 뒤에 누가 고친 건은 남긴다."""
    job = svc.get_or_404(db, job_id)
    svc.start_rollback(db, job, actor, ctx, bg)
    return job
