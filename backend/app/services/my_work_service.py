"""내 업무(My Work, FR-D-01·02) — 내 할일 + 내 담당 인수인계 + 내가 확인할 인수인계.

일정(Schedule)은 Phase 7 에서 같은 형식으로 덧붙인다(source=schedule 은 지금 빈 목록).

버킷 규칙(ASSUMPTIONS B-12)
- 기준일: 할일은 마감일(due_date), 인수인계는 수행일(work_date). 확인할 건은 날짜가 없다.
- 지연: 기준일 < 오늘 · 오늘: = 오늘 · 이번주: 오늘 ~ 이번 주 일요일 · 예정: 다음 주 이후
- 확인필요: 인수 확인함에 있는 것(PENDING · REACK_REQUIRED)
- 대기: 할일 상태 WAITING, 인수인계 상태 분류 WAITING
- 완료: 최근 7일 안에 끝낸 할일·인수인계. 나머지 버킷은 안 끝난 것만.
- 전체: 안 끝난 것 전부(날짜 없는 것 포함). 한 건이 여러 버킷에 들 수 있다(오늘은 이번주에도).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import KST, today, week_start
from app.models.handover import Handover
from app.models.reference import HandoverStatus, Priority
from app.models.task import TASK_CANCELED, TASK_CLOSED_STATES, TASK_DONE, TASK_WAITING, Task
from app.models.user import User
from app.services import shift_service

BUCKETS = ("all", "today", "overdue", "this_week", "upcoming", "need_ack", "waiting", "done")
DONE_DAYS = 7
LIMIT = 500
_KIND_ORDER = {"ACK": 0, "TASK": 1, "HANDOVER": 2}


def _buckets(kind: str, due: date | None, *, waiting: bool, done: bool,
             t0: date, week_end: date) -> set[str]:
    if done:
        return {"done"}
    found = {"all"}
    if kind == "ACK":
        return found | {"need_ack"}
    if waiting:
        found.add("waiting")
    if due is not None:
        if due < t0:
            found.add("overdue")
        elif due == t0:
            found.add("today")
        if t0 <= due <= week_end:
            found.add("this_week")
        elif due > week_end:
            found.add("upcoming")
    return found


def collect(db: Session, actor: User, source: str = "all") -> tuple[list[dict[str, Any]], dict]:
    t0 = today()
    week_end = week_start(t0) + timedelta(days=6)
    since = datetime.combine(t0 - timedelta(days=DONE_DAYS), time.min, tzinfo=KST)
    levels = {p.code: p.level for p in db.scalars(select(Priority))}
    rows: list[dict[str, Any]] = []

    if source in ("all", "task"):
        tasks = db.scalars(select(Task).where(
            Task.assignee_id == actor.id, Task.is_deleted.is_(False), Task.status != TASK_CANCELED,
            or_(Task.status != TASK_DONE, Task.completed_at >= since)))
        for t in tasks:
            done = t.status == TASK_DONE
            rows.append({
                "kind": "TASK", "id": t.id, "title": t.title,
                "company": t.company.name if t.company else None,
                "due": t.due_date, "status": t.status, "status_code": t.status,
                "priority_code": t.priority_code,
                "is_overdue": bool(t.due_date and t.due_date < t0 and t.status not in TASK_CLOSED_STATES),
                "handover_id": t.handover_id,
                "checklist_total": len(t.checklists),
                "checklist_done": sum(1 for c in t.checklists if c.is_done),
                "_buckets": _buckets("TASK", t.due_date, waiting=t.status == TASK_WAITING,
                                     done=done, t0=t0, week_end=week_end),
            })

    if source in ("all", "handover"):
        handovers = db.execute(
            select(Handover, HandoverStatus.category)
            .join(HandoverStatus, HandoverStatus.code == Handover.status_code)
            .where(Handover.assignee_id == actor.id, Handover.is_deleted.is_(False),
                   or_(HandoverStatus.category != "CLOSED",
                       Handover.updated_at >= since))).all()
        for h, category in handovers:
            done = category == "CLOSED"
            rows.append({
                "kind": "HANDOVER", "id": h.id, "title": h.title,
                "company": h.company.name if h.company else None,
                "due": h.work_date, "status": h.status.name if h.status else h.status_code,
                "status_code": h.status_code, "priority_code": h.priority_code,
                "is_overdue": bool(h.work_date and h.work_date < t0 and not done),
                "handover_id": h.id,
                "_buckets": _buckets("HANDOVER", h.work_date, waiting=category == "WAITING",
                                     done=done, t0=t0, week_end=week_end),
            })

    if source in ("all", "ack"):
        for a in shift_service.inbox(db, actor):
            rows.append({
                "kind": "ACK", "id": a["handover_id"], "title": a["title"], "company": a["company"],
                "due": None, "status": a["status"], "status_code": None,
                "priority_code": a["priority_code"], "is_overdue": False,
                "handover_id": a["handover_id"], "ack_state": a["state"],
                "from_user": a["from_user"], "session_id": a["session_id"],
                "_buckets": _buckets("ACK", None, waiting=False, done=False, t0=t0, week_end=week_end),
            })

    counts = {b: sum(1 for r in rows if b in r["_buckets"]) for b in BUCKETS}

    def order(r: dict[str, Any]):
        return (not r["is_overdue"], r["due"] is None, r["due"] or date.max,
                levels.get(r["priority_code"] or "", 9), _KIND_ORDER[r["kind"]], r["id"])

    rows.sort(key=order)
    return rows, {"today": t0, "week_end": week_end, "counts": counts}


def my_work(db: Session, actor: User, bucket: str = "all", source: str = "all") -> dict[str, Any]:
    rows, meta = collect(db, actor, source)
    picked = [r for r in rows if bucket in r["_buckets"]]
    if bucket == "done":
        picked.sort(key=lambda r: (r["kind"], -r["id"]))
    items = [{k: v for k, v in r.items() if not k.startswith("_")} for r in picked[:LIMIT]]
    return {"bucket": bucket, "source": source, **meta, "items": items}
