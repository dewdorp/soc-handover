"""Excel Import 수명주기 — 8단계 마법사의 상태 전이를 여기서만 결정한다.

    UPLOAD+ANALYZE ─► MAPPED ─stage─► DEDUPED ─commit─► COMPLETED ─rollback─► ROLLED_BACK
                        ▲                 │ ▲
                        └── mapping ──────┘ └── value-map / decisions (다시 prepare)

긴 작업(stage·prepare·commit·rollback)은 jobs.runner 가 응답 뒤에 돌린다. 여기서는
'지금 그 작업을 시작해도 되는 상태인가'만 판단하고 점유(claim)한다.
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.audit import actions
from app.audit.recorder import record
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.time import now
from app.importers.excel import aliases as al
from app.importers.excel import pipeline as pl
from app.importers.excel.normalize import CREATE_COMPANY
from app.importers.excel.reader import analyze, suggest_mapping
from app.jobs import runner
from app.models.importjob import (JOB_ANALYZED, JOB_CANCELED, JOB_COMPLETED, JOB_DEDUPED,
                                  JOB_FAILED, JOB_MAPPED, JOB_ROLLED_BACK, JOB_RUNNING,
                                  JOB_STAGED, ExcelImportError,
                                  ExcelImportJob, ExcelImportRow)
from app.models.reference import Company, HandoverStatus
from app.models.user import User
from app.utils.fingerprint import norm

EXCEL_EXT = (".xlsx", ".xlsm")
CSV_EXT = (".csv", ".tsv")
ALLOWED_EXT = EXCEL_EXT + CSV_EXT
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"   # 구형 .xls

PHASE_STAGE = "STAGE"
PHASE_PREPARE = "PREPARE"
PHASE_COMMIT = "COMMIT"
PHASE_ROLLBACK = "ROLLBACK"


# --------------------------------------------------------------------------- 조회

def get_or_404(db: Session, job_id: int) -> ExcelImportJob:
    job = db.get(ExcelImportJob, job_id)
    if job is None:
        raise NotFound("Import 작업을 찾을 수 없습니다.")
    return job


def list_jobs(db: Session, limit: int = 50) -> list[ExcelImportJob]:
    return list(db.scalars(select(ExcelImportJob)
                           .order_by(ExcelImportJob.id.desc()).limit(limit)))


# --------------------------------------------------------------------------- ① UPLOAD + ② ANALYZE

async def upload(db: Session, file: UploadFile, actor: User) -> ExcelImportJob:
    name = Path(file.filename or "upload.xlsx").name
    if not name.lower().endswith(ALLOWED_EXT):
        if name.lower().endswith(".xls"):
            raise ValidationFailed("구형 .xls 는 읽을 수 없습니다. Excel 에서 '다른 이름으로 저장 → "
                                   "Excel 통합 문서(*.xlsx)' 로 저장한 뒤 올려 주십시오.")
        raise ValidationFailed("Excel(.xlsx) 또는 CSV(.csv · .tsv) 파일만 올릴 수 있습니다.",
                               detail={"allowed": list(ALLOWED_EXT)})
    is_csv = name.lower().endswith(CSV_EXT)

    code = f"IMP-{now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    folder = settings.imports_dir / code
    folder.mkdir(parents=True, exist_ok=True)
    # 저장 이름은 사용자 입력을 쓰지 않는다(경로 조작 방지).
    stored = folder / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"

    limit = settings.IMPORT_MAX_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        with stored.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                if not head:
                    head = chunk[:8]
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed(f"파일이 너무 큽니다(최대 {settings.IMPORT_MAX_MB}MB).")
                digest.update(chunk)
                out.write(chunk)
        if not is_csv:
            if head.startswith(_OLE_MAGIC):
                raise ValidationFailed("확장자는 .xlsx 지만 실제로는 구형 .xls 파일입니다. "
                                       "Excel 에서 xlsx 로 다시 저장해 주십시오.")
            if not head.startswith(_ZIP_MAGIC):
                raise ValidationFailed("Excel 파일이 아닙니다(내용이 xlsx 형식이 아님).")
        elif head.startswith(_ZIP_MAGIC) or head.startswith(_OLE_MAGIC):
            raise ValidationFailed("확장자는 CSV 지만 실제 내용은 Excel 파일입니다. "
                                   "확장자를 .xlsx 로 바꾸거나 CSV 로 다시 저장해 주십시오.")
        try:
            sheets = analyze(stored, db=db, original_name=name)
        except Exception as exc:
            kind = "CSV" if is_csv else "Excel"
            raise ValidationFailed(f"{kind} 파일을 열 수 없습니다: {type(exc).__name__}") from exc
        if is_csv and not sheets[0]["headers"]:
            raise ValidationFailed("CSV 에서 컬럼(헤더)을 찾지 못했습니다. 첫 줄에 컬럼 이름이 있는지 확인해 주십시오.")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    headers: list[str] = []
    for sheet in sheets:
        for h in sheet["headers"]:
            if h not in headers:
                headers.append(h)

    sha = digest.hexdigest()
    warnings: list[str] = []
    earlier = db.scalar(select(ExcelImportJob).where(
        ExcelImportJob.file_sha256 == sha, ExcelImportJob.status == JOB_COMPLETED))
    if earlier is not None:
        warnings.append(f"같은 파일이 이미 가져와졌습니다({earlier.job_code}). "
                        "그대로 진행하면 중복 검사에서 대부분 '중복 의심'으로 표시됩니다.")

    job = ExcelImportJob(
        job_code=code, file_name=name[:255], stored_path=str(stored), file_sha256=sha,
        status=JOB_ANALYZED, created_by=actor.id,
        sheet_summary={"sheets": sheets, "headers": headers, "size_bytes": size,
                       "warnings": warnings},
        column_mapping=suggest_mapping([s["headers"] for s in sheets], db=db),
        options={"sheets": [s["name"] for s in sheets if s["recognized"] >= 2],
                 "default_status": "DONE", "value_map": {}},
    )
    db.add(job)
    db.flush()
    return job


def mapping_targets() -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in al.TARGETS]


# --------------------------------------------------------------------------- ③ MAPPING

def set_mapping(db: Session, job: ExcelImportJob, *, sheets: list[str],
                column_mapping: dict[str, str | None], default_status: str,
                default_year: int | None) -> ExcelImportJob:
    _require_status(job, {JOB_ANALYZED, JOB_MAPPED, JOB_STAGED, JOB_DEDUPED, JOB_FAILED},
                    action="매핑 변경")
    if job.status == JOB_FAILED and job.phase == PHASE_COMMIT:
        raise Conflict("가져오기 도중 실패한 작업은 매핑을 바꿀 수 없습니다. 다시 가져오기를 실행하십시오.")

    known = {s["name"] for s in (job.sheet_summary or {}).get("sheets", [])}
    unknown = [s for s in sheets if s not in known]
    if unknown:
        raise ValidationFailed("파일에 없는 Sheet 입니다.", detail={"sheets": unknown})

    headers = set((job.sheet_summary or {}).get("headers", []))
    cleaned: dict[str, str | None] = {}
    for header, target in column_mapping.items():
        if header not in headers:
            raise ValidationFailed(f"파일에 없는 컬럼입니다: {header}")
        target = target or None
        if target is not None and target not in al.TARGET_NAMES:
            raise ValidationFailed(f"알 수 없는 대상 필드입니다: {target}",
                                   detail={"allowed": sorted(al.TARGET_NAMES)})
        cleaned[header] = target

    # 한 필드에 컬럼 하나는 Sheet 단위로 검사한다(연도별 Sheet 의 표기 차이 허용).
    sheet_headers = {s["name"]: s["headers"] for s in (job.sheet_summary or {}).get("sheets", [])}
    for sheet in sheets:
        seen: dict[str, str] = {}
        for header in sheet_headers.get(sheet, []):
            target = cleaned.get(header)
            if not target:
                continue
            if target in seen:
                raise ValidationFailed(
                    f"'{sheet}' Sheet 에서 '{seen[target]}' 과(와) '{header}' 가 "
                    f"같은 필드({target})에 매핑되었습니다.")
            seen[target] = header
        if al.F_CONTENT not in seen and al.F_TITLE not in seen:
            raise ValidationFailed(
                f"'{sheet}' Sheet 에서 '내용' 또는 '제목' 중 하나는 반드시 매핑해야 합니다.")
    if db.get(HandoverStatus, default_status) is None:
        raise ValidationFailed(f"존재하지 않는 상태 코드입니다: {default_status}")

    options = dict(job.options or {})
    sheets_changed = sorted(options.get("sheets") or []) != sorted(sheets)
    options.update(sheets=sheets, default_status=default_status, default_year=default_year)
    job.options = options
    job.column_mapping = cleaned
    flag_modified(job, "options")
    flag_modified(job, "column_mapping")

    already_staged = job.status in (JOB_STAGED, JOB_DEDUPED) or (
        job.status == JOB_FAILED and job.phase == PHASE_PREPARE)
    # Sheet 선택이 그대로면 원본을 다시 읽을 필요 없이 해석(prepare)만 다시 하면 된다.
    job.status = JOB_STAGED if already_staged and not sheets_changed else JOB_MAPPED
    job.phase = None
    return job


# --------------------------------------------------------------------------- ④~⑥ STAGE / PREPARE

def start_stage(db: Session, job: ExcelImportJob, bg: BackgroundTasks) -> None:
    _require_retryable(job, {JOB_MAPPED, JOB_STAGED, JOB_DEDUPED}, {PHASE_STAGE, PHASE_PREPARE})
    _claim(db, job, {JOB_MAPPED, JOB_STAGED, JOB_DEDUPED, JOB_FAILED}, PHASE_STAGE)

    def work(s: Session, j: ExcelImportJob, progress) -> dict[str, Any]:
        staged = pl.stage(s, j, lambda p: progress(p // 2))
        j.phase = PHASE_PREPARE
        s.commit()
        prepared = pl.prepare(s, j, lambda p: progress(50 + p // 2))
        return {**staged, **prepared}

    bg.add_task(runner.run, job.id, work, success_status=JOB_DEDUPED)


def start_prepare(db: Session, job: ExcelImportJob, bg: BackgroundTasks) -> None:
    _require_retryable(job, {JOB_STAGED, JOB_DEDUPED}, {PHASE_PREPARE})
    _claim(db, job, {JOB_STAGED, JOB_DEDUPED, JOB_FAILED}, PHASE_PREPARE)
    bg.add_task(runner.run, job.id, pl.prepare, success_status=JOB_DEDUPED)


def value_stats(db: Session, job: ExcelImportJob, field: str) -> list[dict[str, Any]]:
    """값 매핑 화면 — 엑셀에 적힌 관계사/진행상황 원문별 건수와 현재 연결 대상.

    표기만 다른 값('A보안', 'a보안 ')은 **한 줄로 묶는다.** 따로 보여주면 사용자가 둘 다
    '새로 등록'을 골라 같은 회사가 두 개 생긴다. 대표 표기는 가장 많이 쓰인 것이다.
    """
    _require_status(job, {JOB_DEDUPED, JOB_STAGED}, action="값 매핑 조회")
    raw_map = ((job.options or {}).get("value_map") or {}).get(field) or {}
    value_map = {norm(k): v for k, v in raw_map.items()}

    if field == "company":
        name = ExcelImportRow.normalized["company_name"].as_string()
        cid = ExcelImportRow.normalized["company_id"].as_integer()
        rows = db.execute(select(name, cid, func.count())
                          .where(ExcelImportRow.job_id == job.id, name.is_not(None))
                          .group_by(name, cid)).all()
        labels = {c.id: c.name for c in db.scalars(select(Company))}
        auto = {value: company_id for value, company_id, _ in rows if company_id}
        spellings = [(value, count) for value, _, count in rows]

        def resolve(key: str, variants: list[str]):
            if key in value_map:
                return value_map[key]
            return next((auto[v] for v in variants if v in auto), None)

        def label(target):
            if target == CREATE_COMPANY:
                return "신규 생성"
            return labels.get(target) if isinstance(target, int) else None
    else:
        raw = ExcelImportRow.normalized["status_raw"].as_string()
        spellings = db.execute(select(raw, func.count())
                               .where(ExcelImportRow.job_id == job.id, raw.is_not(None))
                               .group_by(raw)).all()
        lk = pl.build_lookups(db, job)
        names = {s.code: s.name for s in db.scalars(select(HandoverStatus))}

        def resolve(key: str, variants: list[str]):
            return value_map.get(key) or lk.statuses.get(key)

        def label(target):
            return names.get(target)

    groups: dict[str, dict[str, Any]] = {}
    for value, count in spellings:
        g = groups.setdefault(norm(value), {"counts": {}, "count": 0})
        g["counts"][value] = g["counts"].get(value, 0) + count
        g["count"] += count

    out = []
    for key, g in groups.items():
        variants = sorted(g["counts"], key=lambda v: -g["counts"][v])
        target = resolve(key, variants)
        out.append({"value": variants[0], "variants": variants, "count": g["count"],
                    "target": target, "target_label": label(target),
                    "matched": target is not None})
    return sorted(out, key=lambda e: (e["matched"], -e["count"]))


def set_value_map(db: Session, job: ExcelImportJob, field: str,
                  mapping: dict[str, Any], bg: BackgroundTasks) -> None:
    for value, target in mapping.items():
        if target is None:
            continue
        if field == "company":
            if target != CREATE_COMPANY and (not isinstance(target, int)
                                            or db.get(Company, target) is None):
                raise ValidationFailed(f"'{value}' 의 연결 대상 관계사가 없습니다: {target}")
        elif db.get(HandoverStatus, str(target)) is None:
            raise ValidationFailed(f"'{value}' 의 연결 대상 상태 코드가 없습니다: {target}")

    options = dict(job.options or {})
    value_map = dict(options.get("value_map") or {})
    current = dict(value_map.get(field) or {})
    for value, target in mapping.items():
        if target is None:
            current.pop(value, None)
        else:
            current[value] = target
    value_map[field] = current
    options["value_map"] = value_map
    job.options = options
    flag_modified(job, "options")
    db.flush()
    start_prepare(db, job, bg)


def set_decisions(db: Session, job: ExcelImportJob, row_ids: list[int], decision: str) -> int:
    _require_status(job, {JOB_DEDUPED}, action="가져오기 선택")
    rows = db.scalars(select(ExcelImportRow).where(
        ExcelImportRow.job_id == job.id, ExcelImportRow.id.in_(row_ids),
        ExcelImportRow.status != pl.ROW_IMPORTED)).all()
    for row in rows:
        row.decision = decision
    db.flush()
    job.report = {**(job.report or {}), **pl.summarize(db, job)}
    return len(rows)


# --------------------------------------------------------------------------- ⑦ COMMIT

def start_commit(db: Session, job: ExcelImportJob, actor: User, ctx: RequestContext,
                 bg: BackgroundTasks) -> None:
    _require_retryable(job, {JOB_DEDUPED, JOB_CANCELED}, {PHASE_COMMIT})
    _claim(db, job, {JOB_DEDUPED, JOB_FAILED, JOB_CANCELED}, PHASE_COMMIT)
    job.cancel_requested = False      # 다시 시작하면 멈춘 자리에서 이어서 넣는다
    db.commit()
    actor_id = actor.id

    def work(s: Session, j: ExcelImportJob, progress) -> dict[str, Any]:
        who = s.get(User, actor_id)
        stats = pl.commit_rows(s, j, who, progress)
        record(s, action=actions.EXCEL_IMPORT, ctx=ctx, user=who,
               resource_type="IMPORT_JOB", resource_id=j.job_code,
               detail={"file": j.file_name, "sha256": j.file_sha256, **stats})
        return stats

    bg.add_task(runner.run, job.id, work, success_status=JOB_COMPLETED)


# --------------------------------------------------------------------------- 중단 · 폐기

#: 아직 반영하지 않은 단계 — 여기서는 통째로 폐기한다(올린 파일도 지운다)
BEFORE_COMMIT = {JOB_ANALYZED, JOB_MAPPED, JOB_STAGED, JOB_DEDUPED}


def cancel(db: Session, job: ExcelImportJob, actor: User,
           ctx: RequestContext | None = None) -> dict[str, Any]:
    """잘못 올린 작업을 멈춘다.

    · 반영 전: 통째로 **폐기**한다 — staging 행 · 오류 목록 · 올린 파일까지 지운다.
      인수인계는 아직 한 건도 만들지 않았으므로 되돌릴 것이 없다.
    · 반영 중: **배치 경계에서** 멈추라고 표시만 한다. 이미 들어간 행은 그대로 두고
      (ROW_IMPORTED 로 확정되어 다시 넣지 않는다) 남은 행은 '반영'을 다시 누르면 이어서 넣는다.
    · 반영이 끝난 뒤에는 중단이 아니라 되돌리기(rollback)를 쓴다.
    """
    if job.status == JOB_RUNNING and job.phase == PHASE_COMMIT:
        job.cancel_requested = True
        db.flush()
        record(db, action=actions.EXCEL_IMPORT, ctx=ctx, user=actor,
               resource_type="IMPORT_JOB", resource_id=job.job_code,
               detail={"op": "cancel_requested", "file": job.file_name})
        return {"mode": "stopping", "status": job.status,
                "message": "진행 중인 배치를 끝내고 멈춥니다. 이미 반영된 건은 그대로 둡니다."}

    if job.status == JOB_RUNNING:
        # STAGE · PREPARE 는 인수인계를 만들지 않는다 — 표시해 두면 다음 경계에서 멈춘다
        job.cancel_requested = True
        db.flush()
        return {"mode": "stopping", "status": job.status,
                "message": "진행 중인 단계를 끝내고 멈춥니다."}

    _require_status(job, BEFORE_COMMIT | {JOB_FAILED, JOB_CANCELED}, action="중단")
    removed_rows = db.query(ExcelImportRow).filter(ExcelImportRow.job_id == job.id).delete()
    db.query(ExcelImportError).filter(ExcelImportError.job_id == job.id).delete()
    Path(job.stored_path).unlink(missing_ok=True)
    job.status = JOB_CANCELED
    job.phase = None
    job.cancel_requested = False
    job.finished_at = now()
    job.report = {**(job.report or {}), "discarded_rows": removed_rows}
    db.flush()
    record(db, action=actions.EXCEL_IMPORT, ctx=ctx, user=actor,
           resource_type="IMPORT_JOB", resource_id=job.job_code,
           detail={"op": "discarded", "file": job.file_name, "rows": removed_rows})
    return {"mode": "discarded", "status": JOB_CANCELED, "discarded_rows": removed_rows,
            "message": "올린 파일과 임시 자료를 지웠습니다. 인수인계에는 아무것도 반영되지 않았습니다."}


# --------------------------------------------------------------------------- ROLLBACK

def start_rollback(db: Session, job: ExcelImportJob, actor: User, ctx: RequestContext,
                   bg: BackgroundTasks) -> None:
    _require_retryable(job, {JOB_COMPLETED}, {PHASE_ROLLBACK})
    _claim(db, job, {JOB_COMPLETED, JOB_FAILED}, PHASE_ROLLBACK)
    actor_id = actor.id

    def work(s: Session, j: ExcelImportJob, progress) -> dict[str, Any]:
        who = s.get(User, actor_id)
        stats = pl.rollback(s, j, who)
        # 고위험 행위: 감사 기록이 실패하면 롤백 자체도 되돌린다.
        record(s, action=actions.EXCEL_IMPORT_ROLLBACK, ctx=ctx, user=who,
               resource_type="IMPORT_JOB", resource_id=j.job_code, detail=stats)
        return {"rollback": stats}

    bg.add_task(runner.run, job.id, work, success_status=JOB_ROLLED_BACK)


# --------------------------------------------------------------------------- 조회용

def rows_page(db: Session, job: ExcelImportJob, *, kind: str, sheet: str | None,
              page: int, size: int) -> tuple[list[ExcelImportRow], int, set[int]]:
    stmt = select(ExcelImportRow).where(ExcelImportRow.job_id == job.id)
    if sheet:
        stmt = stmt.where(ExcelImportRow.sheet_name == sheet)
    if kind == "error":
        stmt = stmt.where(ExcelImportRow.status == pl.ROW_ERROR)
    elif kind == "warning":
        stmt = stmt.where(ExcelImportRow.status == pl.ROW_WARNING)
    elif kind == "duplicate":
        stmt = stmt.where(ExcelImportRow.dup_type != pl.DUP_NONE)
    elif kind == "import":
        stmt = stmt.where(pl.will_import_condition())
    elif kind == "skip":
        stmt = stmt.where(~pl.will_import_condition(), ExcelImportRow.status != pl.ROW_IMPORTED)
    elif kind == "imported":
        stmt = stmt.where(ExcelImportRow.status == pl.ROW_IMPORTED)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(ExcelImportRow.id)
                           .offset((page - 1) * size).limit(size)))
    ids = [r.id for r in rows]
    importing = set(db.scalars(select(ExcelImportRow.id).where(
        ExcelImportRow.id.in_(ids), pl.will_import_condition()))) if ids else set()
    return rows, total, importing


def errors_page(db: Session, job: ExcelImportJob, page: int, size: int):
    stmt = select(ExcelImportError).where(ExcelImportError.job_id == job.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(ExcelImportError.id)
                           .offset((page - 1) * size).limit(size)))
    return rows, total


def report(db: Session, job: ExcelImportJob) -> dict[str, Any]:
    live = pl.summarize(db, job) if job.status != JOB_ANALYZED else {}
    return {"job_code": job.job_code, "status": job.status, "phase": job.phase,
            "file_name": job.file_name, **(job.report or {}), **live}


def errors_workbook(db: Session, job: ExcelImportJob) -> Path:
    """실패행 Excel — 사용자가 고쳐서 다시 올릴 수 있게 원본 컬럼을 그대로 싣는다."""
    import xlsxwriter

    out = settings.exports_dir / f"import-errors-{job.job_code}-{uuid.uuid4().hex[:6]}.xlsx"
    headers: list[str] = list((job.sheet_summary or {}).get("headers", []))
    wb = xlsxwriter.Workbook(str(out), {"constant_memory": True,
                                        "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet("실패행")
    bold = wb.add_format({"bold": True, "bg_color": "#FDE2E2"})
    columns = ["Sheet", "행 번호", "오류 코드", "오류 내용", "문제 컬럼", *headers]
    for c, name in enumerate(columns):
        ws.write_string(0, c, name, bold)

    r = 1
    last_id = 0
    while True:
        chunk = db.execute(
            select(ExcelImportError, ExcelImportRow.raw)
            .join(ExcelImportRow, ExcelImportRow.id == ExcelImportError.row_id, isouter=True)
            .where(ExcelImportError.job_id == job.id, ExcelImportError.id > last_id)
            .order_by(ExcelImportError.id).limit(1000)).all()
        if not chunk:
            break
        for err, raw in chunk:
            values = [err.sheet_name or "", str(err.source_row or ""), err.error_code,
                      err.message, err.column_name or ""]
            values += ["" if (raw or {}).get(h) is None else str(raw[h]) for h in headers]
            for c, value in enumerate(values):
                ws.write_string(r, c, value)
            r += 1
        last_id = chunk[-1][0].id
    wb.close()
    return out


# --------------------------------------------------------------------------- 내부

def _require_status(job: ExcelImportJob, allowed: set[str], *, action: str) -> None:
    if job.status not in allowed:
        raise Conflict(f"현재 상태({job.status})에서는 {action}을(를) 할 수 없습니다.",
                       detail={"status": job.status, "phase": job.phase,
                               "allowed": sorted(allowed)})


def _require_retryable(job: ExcelImportJob, allowed: set[str], retry_phases: set[str]) -> None:
    """정상 상태이거나, 같은 단계에서 실패한 경우에만 다시 시작할 수 있다."""
    if job.status in allowed:
        return
    if job.status == JOB_FAILED and job.phase in retry_phases:
        return
    raise Conflict(f"현재 상태({job.status})에서는 이 작업을 시작할 수 없습니다.",
                   detail={"status": job.status, "phase": job.phase})


def _claim(db: Session, job: ExcelImportJob, allowed_from: set[str], phase: str) -> None:
    if not runner.claim(db, job.id, allowed_from, phase):
        raise Conflict("이미 다른 작업이 진행 중입니다. 잠시 후 다시 확인하십시오.")
    # 응답 뒤에 도는 작업은 별도 세션이다. 점유 사실을 먼저 확정해야 그쪽이 본다.
    db.commit()
    db.refresh(job)
