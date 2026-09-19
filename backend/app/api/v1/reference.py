"""기준 정보 라우터: 관계사 · 상태 · 중요도 · 교대 · 태그."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import get_current_user, require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.reference import Company, HandoverStatus, Priority, Shift, Tag
from app.models.user import User
from app.schemas.reference import (CompanyCreate, CompanyOut, CompanyUpdate, PriorityOut,
                                   ShiftCreate, ShiftOut, ShiftUpdate, StatusOut, StatusUpsert,
                                   TagOut)

router = APIRouter(tags=["reference"], dependencies=[Depends(require_password_changed)])


# ---------------- 관계사 ----------------

@router.get("/companies", response_model=list[CompanyOut])
def list_companies(q: str = Query(default="", max_length=50), active: bool | None = True,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(Company)
    if active is not None:
        stmt = stmt.where(Company.is_active.is_(active))
    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt.order_by(Company.sort_order, Company.name)))


@router.post("/companies", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db),
                   actor: User = Depends(require("company:manage")),
                   ctx: RequestContext = Depends(get_context)):
    if db.scalar(select(Company).where(Company.name == payload.name)):
        raise Conflict("이미 등록된 관계사입니다.")
    company = Company(**payload.model_dump())
    db.add(company)
    db.flush()
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="COMPANY", resource_id=company.id, after=payload.model_dump())
    return company


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db),
                   actor: User = Depends(require("company:manage")),
                   ctx: RequestContext = Depends(get_context)):
    company = db.get(Company, company_id)
    if company is None:
        raise NotFound("관계사를 찾을 수 없습니다.")
    data = payload.model_dump(exclude_unset=True)
    before = {k: getattr(company, k) for k in data}
    for k, v in data.items():
        setattr(company, k, v)
    db.flush()
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="COMPANY", resource_id=company.id, before=before, after=data)
    return company


# ---------------- 상태 ----------------

@router.get("/statuses", response_model=list[StatusOut])
def list_statuses(active: bool | None = None, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    stmt = select(HandoverStatus)
    if active is not None:
        stmt = stmt.where(HandoverStatus.is_active.is_(active))
    return list(db.scalars(stmt.order_by(HandoverStatus.sort_order)))


@router.post("/statuses", response_model=StatusOut, status_code=status.HTTP_201_CREATED)
def upsert_status(payload: StatusUpsert, db: Session = Depends(get_db),
                  actor: User = Depends(require("status:manage")),
                  ctx: RequestContext = Depends(get_context)):
    existing = db.get(HandoverStatus, payload.code)
    data = payload.model_dump()
    if existing:
        before = {k: getattr(existing, k) for k in data}
        for k, v in data.items():
            setattr(existing, k, v)
        row = existing
    else:
        before = None
        row = HandoverStatus(**data)
        db.add(row)
    db.flush()
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="HANDOVER_STATUS", resource_id=row.code, before=before, after=data)
    return row


@router.delete("/statuses/{code}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_status(code: str, db: Session = Depends(get_db),
                      actor: User = Depends(require("status:manage")),
                      ctx: RequestContext = Depends(get_context)):
    row = db.get(HandoverStatus, code)
    if row is None:
        raise NotFound("상태를 찾을 수 없습니다.")
    if row.is_system:
        raise ValidationFailed("시스템 기본 상태는 삭제할 수 없습니다. 비활성화만 가능합니다.")
    row.is_active = False
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor,
           resource_type="HANDOVER_STATUS", resource_id=code, after={"is_active": False})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- 중요도 / 교대 / 태그 ----------------

@router.get("/priorities", response_model=list[PriorityOut])
def list_priorities(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(Priority).order_by(Priority.level)))


@router.get("/shifts", response_model=list[ShiftOut])
def list_shifts(include_inactive: bool = False, db: Session = Depends(get_db),
                _: User = Depends(get_current_user)):
    """기본은 운영 중인 교대만. 비활성 교대는 과거 기록 참조용으로 남아 있다."""
    stmt = select(Shift)
    if not include_inactive:
        stmt = stmt.where(Shift.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Shift.sort_order)))


def _check_schedule(db: Session) -> None:
    from app.services.shift_service import validate_coverage
    db.flush()
    rows = db.scalars(select(Shift).where(Shift.is_active.is_(True))).all()
    validate_coverage([(r.name, r.start_time, r.end_time) for r in rows])


@router.post("/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(payload: ShiftCreate, db: Session = Depends(get_db),
                 actor: User = Depends(require("shift:manage")),
                 ctx: RequestContext = Depends(get_context)):
    if db.scalar(select(Shift).where(Shift.code == payload.code)):
        raise Conflict(f"이미 있는 교대 코드입니다: {payload.code}")
    shift = Shift(**payload.model_dump(), is_active=True,
                  crosses_midnight=payload.end_time <= payload.start_time)
    db.add(shift)
    _check_schedule(db)   # 새 교대가 기존 교대와 겹치면 저장하지 않는다
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor, resource_type="SHIFT",
           resource_id=shift.code, after=payload.model_dump(mode="json"))
    return shift


@router.patch("/shifts/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, payload: ShiftUpdate, db: Session = Depends(get_db),
                 actor: User = Depends(require("shift:manage")),
                 ctx: RequestContext = Depends(get_context)):
    """교대 시간 변경. 바꾼 결과가 하루 24시간을 빈틈·겹침 없이 덮어야 저장된다.

    여러 교대를 함께 바꿔야 할 때(주간을 줄이고 야간을 늘리는 등)는 중간 상태가
    검사에 걸리므로 PUT /shifts 로 한 번에 보낸다.
    """
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise NotFound("교대를 찾을 수 없습니다.")
    changes = payload.model_dump(exclude_unset=True)
    before = {k: str(getattr(shift, k)) for k in changes}
    for key, value in changes.items():
        setattr(shift, key, value)
    shift.crosses_midnight = shift.end_time <= shift.start_time
    _check_schedule(db)
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor, resource_type="SHIFT",
           resource_id=shift.code, before=before,
           after={k: str(v) for k, v in changes.items()})
    return shift


@router.put("/shifts", response_model=list[ShiftOut])
def replace_schedule(payload: list[ShiftCreate], db: Session = Depends(get_db),
                     actor: User = Depends(require("shift:manage")),
                     ctx: RequestContext = Depends(get_context)):
    """교대표 전체를 한 번에 바꾼다. 목록에 없는 교대는 지우지 않고 비활성화한다
    (과거 인계 기록이 그 교대를 가리키고 있을 수 있다)."""
    wanted = {p.code: p for p in payload}
    if len(wanted) != len(payload):
        raise ValidationFailed("교대 코드가 중복되었습니다.")
    before = [{"code": s.code, "start": str(s.start_time), "end": str(s.end_time),
               "active": s.is_active} for s in db.scalars(select(Shift))]
    for shift in db.scalars(select(Shift)).all():
        spec = wanted.pop(shift.code, None)
        if spec is None:
            shift.is_active = False
            continue
        shift.name, shift.start_time, shift.end_time = spec.name, spec.start_time, spec.end_time
        shift.sort_order, shift.is_active = spec.sort_order, True
        shift.crosses_midnight = spec.end_time <= spec.start_time
    for spec in wanted.values():
        db.add(Shift(**spec.model_dump(), is_active=True,
                     crosses_midnight=spec.end_time <= spec.start_time))
    _check_schedule(db)
    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor, resource_type="SHIFT",
           resource_id="schedule", before={"shifts": before},
           after={"shifts": [p.model_dump(mode="json") for p in payload]})
    return list(db.scalars(select(Shift).where(Shift.is_active.is_(True))
                           .order_by(Shift.sort_order)))


@router.get("/tags", response_model=list[TagOut])
def list_tags(q: str = Query(default="", max_length=50), limit: int = Query(default=30, le=200),
              db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(Tag)
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt.order_by(Tag.usage_count.desc(), Tag.name).limit(limit)))
