"""통계 (UI_STRUCTURE 통계 · Phase 8) — 관계사 · 상태 · 월별, 확인율 · 확인까지 걸린 시간, 지연.

- 기간은 등록일(인수인계) · 전달 시각(교대 인계) · 생성/완료 시각(할일) 기준, 최대 366일.
- 삭제된 인수인계 · 할일은 세지 않는다.
- 확인율: 기간 안에 보낸 교대 인계 항목 중 받는 사람이 확인한 비율. 확인까지 걸린 시간은
  전달 시각 → 그 사람의 확인 시각(재확인은 마지막 확인 기준이라 실제보다 길게 나올 수 있다).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any

from sqlalchemy import case, extract, false, func, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.time import KST, today
from app.models.handover import Handover, HandoverAcknowledgement
from app.models.reference import Company, HandoverStatus
from app.models.shift import ShiftHandover, ShiftHandoverItem, ShiftHandoverRecipient
from app.models.task import TASK_CLOSED_STATES, TASK_DONE, Task

MAX_DAYS = 366


def _range(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise ValidationFailed("기간의 끝이 시작보다 빠를 수 없습니다.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValidationFailed(f"통계 기간은 {MAX_DAYS}일까지입니다.")
    return (datetime.combine(start, time.min, tzinfo=KST),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST))


def summary(db: Session, start: date, end: date) -> dict[str, Any]:
    t_from, t_to = _range(start, end)
    t0 = today()
    in_range = (Handover.is_deleted == false(), Handover.registered_date >= start,
                Handover.registered_date <= end)

    # 관계사 · 상태
    by_company = [
        {"company": name or "(미지정)", "total": total, "open": total - (closed or 0), "closed": closed or 0}
        for name, total, closed in db.execute(
            select(Company.name, func.count(Handover.id),
                   func.sum(case((HandoverStatus.category == "CLOSED", 1), else_=0)))
            .select_from(Handover)
            .join(HandoverStatus, HandoverStatus.code == Handover.status_code)
            .outerjoin(Company, Company.id == Handover.company_id)
            .where(*in_range).group_by(Company.name).order_by(func.count(Handover.id).desc()))
    ]
    by_status = [
        {"code": code, "name": name, "category": category, "count": count}
        for code, name, category, count in db.execute(
            select(HandoverStatus.code, HandoverStatus.name, HandoverStatus.category, func.count(Handover.id))
            .join(Handover, Handover.status_code == HandoverStatus.code)
            .where(*in_range)
            .group_by(HandoverStatus.code, HandoverStatus.name, HandoverStatus.category,
                      HandoverStatus.sort_order)
            .order_by(HandoverStatus.sort_order))
    ]

    # 월별(기간 안) — 등록 건수
    y, m = extract("year", Handover.registered_date), extract("month", Handover.registered_date)
    by_month = [{"month": f"{int(yy):04d}-{int(mm):02d}", "count": count}
                for yy, mm, count in db.execute(select(y, m, func.count(Handover.id)).where(*in_range)
                                                .group_by(y, m).order_by(y, m))]

    # 교대 인계 확인율 · 걸린 시간
    # 인수자마다 한 줄 — 여러 명에게 넘긴 인계는 사람 수만큼 확인해야 한다.
    items = db.execute(
        select(ShiftHandoverRecipient.user_id, ShiftHandover.sent_at,
               ShiftHandoverItem.handover_id)
        .select_from(ShiftHandover)
        .join(ShiftHandoverItem, ShiftHandoverItem.session_id == ShiftHandover.id)
        .join(ShiftHandoverRecipient, ShiftHandoverRecipient.session_id == ShiftHandover.id)
        .join(Handover, Handover.id == ShiftHandoverItem.handover_id)
        .where(ShiftHandover.sent_at >= t_from, ShiftHandover.sent_at < t_to,
               Handover.is_deleted == false())).all()
    acks = {(a.handover_id, a.user_id): a for a in db.scalars(
        select(HandoverAcknowledgement).where(
            HandoverAcknowledgement.handover_id.in_({i.handover_id for i in items} or {0})))}
    minutes: list[float] = []
    acked = 0
    for user_id, sent_at, handover_id in items:
        ack = acks.get((handover_id, user_id))
        if ack is not None and ack.acked_at is not None and ack.acked_at >= sent_at:
            acked += 1
            minutes.append((ack.acked_at - sent_at).total_seconds() / 60)
    ack_stats = {
        "items": len(items), "acked": acked,
        "rate": round(acked / len(items) * 100, 1) if items else None,
        "median_minutes": round(median(minutes), 1) if minutes else None,
        "avg_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "pending_now": db.scalar(select(func.count()).select_from(HandoverAcknowledgement)
                                 .join(Handover, Handover.id == HandoverAcknowledgement.handover_id)
                                 .where(HandoverAcknowledgement.state != "ACKED",
                                        Handover.is_deleted == false())) or 0,
    }

    # 지금 지연 중
    overdue = {
        "handovers": db.scalar(select(func.count()).select_from(Handover)
                               .join(HandoverStatus, HandoverStatus.code == Handover.status_code)
                               .where(Handover.is_deleted == false(), HandoverStatus.category != "CLOSED",
                                      Handover.work_date < t0)) or 0,
        "tasks": db.scalar(select(func.count()).select_from(Task)
                           .where(Task.is_deleted == false(), Task.status.notin_(TASK_CLOSED_STATES),
                                  Task.due_date < t0)) or 0,
    }

    # 할일
    created = db.scalar(select(func.count()).select_from(Task).where(
        Task.is_deleted == false(), Task.created_at >= t_from, Task.created_at < t_to)) or 0
    done_rows = db.execute(select(Task.created_at, Task.completed_at).where(
        Task.is_deleted == false(), Task.status == TASK_DONE,
        Task.completed_at >= t_from, Task.completed_at < t_to)).all()
    hours = [(c2 - c1).total_seconds() / 3600 for c1, c2 in done_rows if c1 and c2 and c2 >= c1]
    tasks = {"created": created, "completed": len(done_rows),
             "median_hours": round(median(hours), 1) if hours else None}

    return {"start": start, "end": end, "total": sum(r["total"] for r in by_company),
            "by_company": by_company, "by_status": by_status, "by_month": by_month,
            "ack": ack_stats, "overdue": overdue, "tasks": tasks}
