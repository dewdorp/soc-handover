"""Import 파이프라인의 DB 작업 — STAGE · PREPARE(검증+중복) · COMMIT · ROLLBACK.

여기 함수들은 긴 작업을 chunk 단위로 나눠 **chunk 마다 commit** 한다. 진행률을 폴링하는
화면이 멈춘 것처럼 보이지 않게 하고, 중간에 실패해도 이미 처리한 부분을 잃지 않게 한다.
COMMIT 은 행 단위로 멱등이라(IMPORTED 인 행은 건너뜀) 실패 후 다시 눌러도 두 번 들어가지 않는다.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.time import now
from app.importers.excel import aliases as al
from app.importers.excel.normalize import CREATE_COMPANY, Lookups, normalize_row
from app.importers.excel.reader import iter_rows
from app.models.handover import CHANGE_DELETE, CHANGE_IMPORT, Handover, HandoverVersion
from app.models.importjob import ExcelImportError, ExcelImportJob, ExcelImportRow
from app.models.reference import Company, HandoverStatus, Priority
from app.models.user import User
from app.utils.fingerprint import norm

Progress = Callable[[int], None]

STAGE_BATCH = 1000
PREPARE_BATCH = 1000
COMMIT_BATCH = 500

ROW_STAGED = "STAGED"
ROW_VALID = "VALID"
ROW_WARNING = "WARNING"
ROW_ERROR = "ERROR"
ROW_IMPORTED = "IMPORTED"

DUP_NONE = "NONE"
DUP_BATCH = "BATCH"        # 같은 파일 안에서 반복
DUP_EXISTING = "EXISTING"  # 이미 시스템에 있음

DEC_PENDING = "PENDING"    # 사용자가 고르지 않음 → 기본 규칙을 따른다
DEC_IMPORT = "IMPORT"
DEC_SKIP = "SKIP"

UNSPECIFIED_COMPANY = "미지정"


def will_import_condition():
    """실제로 가져갈 행. 오류 행은 사용자가 IMPORT 를 골라도 못 들어간다.

    중복 의심은 기본 제외 — 같은 파일을 두 번 올려 전부 두 벌이 되는 사고를 막는다.
    사람이 '그래도 가져온다'를 고른 경우에만 들어간다.
    """
    return and_(
        ExcelImportRow.status.in_((ROW_VALID, ROW_WARNING)),
        (ExcelImportRow.decision == DEC_IMPORT)
        | ((ExcelImportRow.decision == DEC_PENDING) & (ExcelImportRow.dup_type == DUP_NONE)),
    )


# --------------------------------------------------------------------------- STAGE

def stage(db: Session, job: ExcelImportJob, progress: Progress) -> dict[str, int]:
    """선택된 Sheet 의 원본 행을 그대로 staging 에 넣는다. 해석은 하지 않는다."""
    db.execute(delete(ExcelImportError).where(ExcelImportError.job_id == job.id))
    db.execute(delete(ExcelImportRow).where(ExcelImportRow.job_id == job.id))
    db.commit()

    options = job.options or {}
    sheets: list[str] = options.get("sheets") or []
    summary = {s["name"]: s for s in (job.sheet_summary or {}).get("sheets", [])}
    estimated = sum(summary.get(name, {}).get("estimated_rows", 0) for name in sheets) or 1

    path = Path(job.stored_path)
    staged = blank = 0
    batch: list[dict[str, Any]] = []

    def flush() -> None:
        if batch:
            db.execute(insert(ExcelImportRow), batch)
            db.commit()
            batch.clear()
            progress(min(99, int((staged + blank) * 100 / estimated)))

    for sheet in sheets:
        header_row = int(summary.get(sheet, {}).get("header_row") or 1)
        for excel_row, raw in iter_rows(path, sheet, header_row):
            if not raw:
                blank += 1
                continue
            batch.append({"job_id": job.id, "sheet_name": sheet, "source_row": excel_row,
                          "raw": raw, "status": ROW_STAGED, "dup_type": DUP_NONE,
                          "decision": DEC_PENDING})
            staged += 1
            if len(batch) >= STAGE_BATCH:
                flush()
    flush()

    job.total_rows = staged
    job.skipped_rows = blank
    return {"staged": staged, "blank": blank}


# --------------------------------------------------------------------------- PREPARE

def build_lookups(db: Session, job: ExcelImportJob) -> Lookups:
    companies: dict[str, int] = {}
    for c in db.scalars(select(Company).where(Company.is_active.is_(True))):
        for label in (c.name, c.short_name, c.code):
            if label:
                companies.setdefault(norm(label), c.id)

    # 별칭 사전(정규화된 문구 → 코드)에 관리자가 만든 상태의 이름·코드를 더한다.
    statuses: dict[str, str] = dict(al.build_lookup(al.status_aliases(db)))
    for s in db.scalars(select(HandoverStatus).where(HandoverStatus.is_active.is_(True))):
        statuses.setdefault(norm(s.name), s.code)
        statuses.setdefault(norm(s.code), s.code)

    priorities: dict[str, str] = dict(al.build_lookup(al.PRIORITY_ALIASES))
    for p in db.scalars(select(Priority)):
        priorities.setdefault(norm(p.name), p.code)
        priorities.setdefault(norm(p.code), p.code)

    users: dict[str, int] = {}
    for u in db.scalars(select(User).where(User.is_active.is_(True))):
        users.setdefault(norm(u.display_name), u.id)
        users.setdefault(norm(u.username), u.id)

    options = job.options or {}
    value_map = options.get("value_map") or {}
    return Lookups(
        companies=companies, statuses=statuses, priorities=priorities, users=users,
        company_value_map={norm(k): v for k, v in (value_map.get("company") or {}).items()},
        status_value_map={norm(k): v for k, v in (value_map.get("status") or {}).items()},
        default_status=options.get("default_status") or "DONE",
        default_year=options.get("default_year"),
    )


def prepare(db: Session, job: ExcelImportJob, progress: Progress) -> dict[str, int]:
    """정규화 + 검증 + 중복 판정. raw 에서 매번 다시 계산하므로 몇 번을 돌려도 같다.

    사용자가 직접 고른 decision(IMPORT/SKIP)은 건드리지 않는다. 값 매핑을 고치고 다시
    돌렸다고 사람이 한 선택이 사라지면 안 된다.
    """
    mapping: dict[str, str | None] = job.column_mapping or {}
    lk = build_lookups(db, job)

    db.execute(delete(ExcelImportError).where(ExcelImportError.job_id == job.id))
    db.execute(update(ExcelImportRow)
               .where(ExcelImportRow.job_id == job.id, ExcelImportRow.status != ROW_IMPORTED)
               .values(dup_type=DUP_NONE, dup_handover_id=None))
    db.commit()

    total = job.total_rows or 1
    done = 0
    last_id = 0
    while True:
        rows = db.scalars(
            select(ExcelImportRow)
            .where(ExcelImportRow.job_id == job.id, ExcelImportRow.id > last_id,
                   ExcelImportRow.status != ROW_IMPORTED)
            .order_by(ExcelImportRow.id).limit(PREPARE_BATCH)
        ).all()
        if not rows:
            break
        for row in rows:
            result = normalize_row(row.raw, mapping, row.sheet_name, lk)
            row.normalized = result.normalized
            row.warnings = result.warnings or None
            row.fingerprint = result.fingerprint
            row.status = (ROW_ERROR if result.errors
                          else ROW_WARNING if result.warnings else ROW_VALID)
            for err in result.errors:
                db.add(ExcelImportError(
                    job_id=job.id, row_id=row.id, sheet_name=row.sheet_name,
                    source_row=row.source_row, column_name=err["column"],
                    error_code=err["code"], message=err["message"],
                    raw_value=err["raw_value"]))
        last_id = rows[-1].id
        done += len(rows)
        db.commit()
        progress(min(90, int(done * 90 / total)))

    _mark_duplicates(db, job)
    db.commit()
    return summarize(db, job)


def _mark_duplicates(db: Session, job: ExcelImportJob) -> None:
    candidates = and_(ExcelImportRow.job_id == job.id,
                      ExcelImportRow.fingerprint.is_not(None),
                      ExcelImportRow.status != ROW_IMPORTED)

    # 1) 이미 시스템에 있는 것. 이 job 이 넣은 행은 '기존'이 아니다(부분 실패 후 재시도 대비).
    existing = (select(Handover.fingerprint, func.min(Handover.id).label("hid"))
                .where(Handover.is_deleted.is_(False), Handover.fingerprint.is_not(None),
                       (Handover.import_job_id.is_(None)) | (Handover.import_job_id != job.id))
                .group_by(Handover.fingerprint).subquery())
    matches = db.execute(
        select(ExcelImportRow.id, existing.c.hid)
        .join(existing, existing.c.fingerprint == ExcelImportRow.fingerprint)
        .where(candidates)
    ).all()
    for row_id, hid in matches:
        db.execute(update(ExcelImportRow).where(ExcelImportRow.id == row_id)
                   .values(dup_type=DUP_EXISTING, dup_handover_id=hid))

    # 2) 같은 파일 안에서 반복된 것. 첫 행은 살리고 두 번째부터 의심 표시.
    firsts = (select(ExcelImportRow.fingerprint, func.min(ExcelImportRow.id).label("first_id"))
              .where(candidates).group_by(ExcelImportRow.fingerprint)
              .having(func.count() > 1).subquery())
    repeats = db.execute(
        select(ExcelImportRow.id)
        .join(firsts, firsts.c.fingerprint == ExcelImportRow.fingerprint)
        .where(candidates, ExcelImportRow.id != firsts.c.first_id,
               ExcelImportRow.dup_type == DUP_NONE)
    ).scalars().all()
    if repeats:
        db.execute(update(ExcelImportRow).where(ExcelImportRow.id.in_(repeats))
                   .values(dup_type=DUP_BATCH))


def summarize(db: Session, job: ExcelImportJob) -> dict[str, int]:
    base = select(func.count()).select_from(ExcelImportRow).where(ExcelImportRow.job_id == job.id)
    count = lambda *conds: db.scalar(base.where(*conds)) or 0  # noqa: E731
    stats = {
        "total": count(),
        "valid": count(ExcelImportRow.status == ROW_VALID),
        "warning": count(ExcelImportRow.status == ROW_WARNING),
        "error": count(ExcelImportRow.status == ROW_ERROR),
        "duplicate": count(ExcelImportRow.dup_type != DUP_NONE),
        "duplicate_existing": count(ExcelImportRow.dup_type == DUP_EXISTING),
        "duplicate_batch": count(ExcelImportRow.dup_type == DUP_BATCH),
        "imported": count(ExcelImportRow.status == ROW_IMPORTED),
        "will_import": count(will_import_condition()),
        "blank": job.skipped_rows or 0,
    }
    job.error_rows = stats["error"]
    job.duplicate_rows = stats["duplicate"]
    return stats


# --------------------------------------------------------------------------- COMMIT

def _resolve_companies(db: Session, job: ExcelImportJob) -> tuple[dict[str, int], int]:
    """생성하기로 한 관계사를 만들고, 매칭 실패는 '미지정'으로 보낸다. (이름→id, 미지정 id)"""
    unspecified = db.scalar(select(Company).where(Company.name == UNSPECIFIED_COMPANY))
    if unspecified is None:
        unspecified = Company(name=UNSPECIFIED_COMPANY, code="UNSPEC", sort_order=999)
        db.add(unspecified)
        db.flush()

    # 표기만 다른 이름('A보안'/'a보안 ')이 각각 회사로 생기면 안 된다. 정규화 키로 한 번만 만든다.
    by_norm = {norm(c.name): c.id for c in db.scalars(select(Company))}
    created: dict[str, int] = {}
    value_map = ((job.options or {}).get("value_map") or {}).get("company") or {}
    for name, target in value_map.items():
        if target != CREATE_COMPANY:
            continue
        key = norm(name)
        if key in created:
            continue
        company_id = by_norm.get(key)
        if company_id is None:
            company = Company(name=name.strip())
            db.add(company)
            db.flush()
            company_id = by_norm[key] = company.id
        created[key] = company_id
    db.commit()
    return created, unspecified.id


def _search_text(n: dict[str, Any], company_name: str, remark: str | None,
                 names: dict[int, str]) -> str:
    parts = [n.get("title") or "", n.get("content") or "", remark or "", company_name]
    for uid_key, raw_key in (("sender_id", "sender_name_raw"), ("assignee_id", "assignee_name_raw"),
                             ("checker_id", "checker_name_raw")):
        if n.get(uid_key) and names.get(n[uid_key]):
            parts.append(names[n[uid_key]])
        if n.get(raw_key):
            parts.append(n[raw_key])
    return " ".join(p for p in parts if p).strip()


def commit_rows(db: Session, job: ExcelImportJob, actor: User,
                progress: Progress) -> dict[str, int]:
    created_companies, unspecified_id = _resolve_companies(db, job)
    company_names = {c.id: c.name for c in db.scalars(select(Company))}
    user_names = {u.id: u.display_name for u in db.scalars(select(User))}
    reason = f"Excel Import {job.job_code}"

    target_total = db.scalar(select(func.count()).select_from(ExcelImportRow)
                             .where(ExcelImportRow.job_id == job.id,
                                    ExcelImportRow.status != ROW_IMPORTED,
                                    will_import_condition())) or 0
    done = 0
    last_id = 0
    while True:
        rows = db.scalars(
            select(ExcelImportRow)
            .where(ExcelImportRow.job_id == job.id, ExcelImportRow.id > last_id,
                   ExcelImportRow.status != ROW_IMPORTED, will_import_condition())
            .order_by(ExcelImportRow.id).limit(COMMIT_BATCH)
        ).all()
        if not rows:
            break

        stamp = now()
        pairs: list[tuple[ExcelImportRow, Handover]] = []
        for row in rows:
            n = row.normalized or {}
            remark = n.get("remark")
            company_id = n.get("company_id") or created_companies.get(norm(n.get("company_name")))
            if company_id is None:
                company_id = unspecified_id
                if n.get("company_name"):
                    # 원래 관계사 이름을 잃지 않는다. 비고는 검색 대상이라 찾을 수도 있다.
                    tag = f"[원본 관계사: {n['company_name']}]"
                    remark = f"{tag} {remark}" if remark else tag
            handover = Handover(
                company_id=company_id,
                title=n.get("title") or "(제목 없음)",
                content=n.get("content") or "",
                remark=remark,
                status_code=n.get("status_code") or "DONE",
                priority_code=n.get("priority_code") or "NORMAL",
                registered_date=date.fromisoformat(n["registered_date"]),
                work_date=date.fromisoformat(n["work_date"]) if n.get("work_date") else None,
                sender_id=n.get("sender_id"), sender_name_raw=n.get("sender_name_raw"),
                assignee_id=n.get("assignee_id"), assignee_name_raw=n.get("assignee_name_raw"),
                checker_id=n.get("checker_id"), checker_name_raw=n.get("checker_name_raw"),
                current_version_no=1,
                source_file=job.file_name[:255], source_sheet=row.sheet_name[:100],
                source_row=row.source_row, import_job_id=job.id, fingerprint=row.fingerprint,
                created_by=actor.id, updated_by=actor.id,
                search_text=_search_text(n, company_names.get(company_id, ""), remark,
                                         user_names),
            )
            db.add(handover)
            pairs.append((row, handover))
        db.flush()  # id 확보

        from app.services.handover_service import snapshot
        for row, handover in pairs:
            db.add(HandoverVersion(
                handover_id=handover.id, version_no=1, change_type=CHANGE_IMPORT,
                before_data=None, after_data=snapshot(handover),
                changed_fields=[], change_reason=reason,
                changed_by=actor.id, changed_at=stamp))
            row.status = ROW_IMPORTED
            row.handover_id = handover.id
        db.commit()

        last_id = rows[-1].id
        done += len(rows)
        progress(min(99, int(done * 100 / max(target_total, 1))))

    stats = summarize(db, job)
    job.success_rows = stats["imported"]
    stats["committed_now"] = done
    stats["companies_created"] = len(created_companies)
    return stats


# --------------------------------------------------------------------------- ROLLBACK

def rollback(db: Session, job: ExcelImportJob, actor: User) -> dict[str, int]:
    """job 이 넣은 인수인계를 Soft Delete 한다.

    Import 뒤에 **누군가 고친 행은 지우지 않는다**(current_version_no > 1). 되돌리기로
    남의 작업을 날리면 그게 누락이다. 몇 건을 남겼는지 보고서에 적는다.
    """
    reason = f"Excel Import 롤백 {job.job_code}"
    rows = db.scalars(select(Handover).where(Handover.import_job_id == job.id,
                                             Handover.is_deleted.is_(False))).all()
    removed = kept = 0
    stamp = now()
    from app.services.handover_service import snapshot
    for handover in rows:
        if handover.current_version_no > 1:
            kept += 1
            continue
        handover.is_deleted = True
        handover.deleted_at = stamp
        handover.deleted_by = actor.id
        handover.delete_reason = reason
        handover.current_version_no += 1
        db.add(HandoverVersion(
            handover_id=handover.id, version_no=handover.current_version_no,
            change_type=CHANGE_DELETE, before_data={"is_deleted": False},
            after_data=snapshot(handover), changed_fields=["is_deleted"],
            change_reason=reason, changed_by=actor.id, changed_at=stamp))
        removed += 1
    db.flush()
    return {"removed": removed, "kept_modified": kept}
