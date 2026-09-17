"""기준 정보 라우터: 관계사 · 상태 · 중요도 · 교대 · 태그."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.deps import get_current_user, require
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.reference import Company, HandoverStatus, Priority, Shift, Tag
from app.models.user import User
from app.schemas.reference import (CompanyCreate, CompanyOut, CompanyUpdate, PriorityOut,
                                   ShiftOut, StatusOut, StatusUpsert, TagOut)

router = APIRouter(tags=["reference"])


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
def list_shifts(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(Shift).order_by(Shift.sort_order)))


@router.get("/tags", response_model=list[TagOut])
def list_tags(q: str = Query(default="", max_length=50), limit: int = Query(default=30, le=200),
              db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(Tag)
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt.order_by(Tag.usage_count.desc(), Tag.name).limit(limit)))
