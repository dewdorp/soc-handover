"""일정 규칙 — 만들기 · 고치기 · 달력 이동 · 삭제 · 달력 겹쳐 보기 (FR-E, ASSUMPTIONS B-13).

- 시각은 시간대가 붙은 채로 다룬다. 시간대가 없으면 KST. 끝은 포함하지 않는다.
- 하루 종일 일정은 시작일 00:00 ~ 마지막 날 다음 날 00:00 으로 맞춘다.
- 수정·이동은 expected_version 이 맞아야 저장된다(§26).
- 권한: 담당자(owner)·만든 사람, 또는 schedule:update_any(관리자).
- 감사: CALENDAR_CREATE / CALENDAR_UPDATE(달력 이동은 via=drag) / CALENDAR_DELETE.
- 반복 일정은 한 건으로 저장하고, 조회할 때 기간 안의 회차만 펼친다(recurrence.py).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import has_permission
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.core.time import KST, now, today
from app.models.handover import Handover
from app.models.reference import Company, HandoverStatus
from app.models.schedule import Schedule, ScheduleReminder
from app.models.task import TASK_CANCELED, TASK_CLOSED_STATES, TASK_DONE, Task
from app.models.user import User
from app.services import notification_service, recurrence

DEFAULT_LENGTH = timedelta(hours=1)
MAX_LENGTH = timedelta(days=31)
MAX_RANGE_DAYS = 100
MAX_EVENTS = 2000
TRACKED = ("title", "description", "event_type", "start_at", "end_at", "is_all_day", "company_id",
           "owner_id", "recurrence_rule", "color")


# --------------------------------------------------------------------------- 공통

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _snapshot(s: Schedule) -> dict[str, Any]:
    return {k: _jsonable(getattr(s, k)) for k in TRACKED}


def can_edit(actor: User, s: Schedule) -> bool:
    if has_permission(actor.role_code, "schedule:update_any"):
        return True
    return (has_permission(actor.role_code, "schedule:update_own")
            and actor.id in {s.owner_id, s.created_by})


def _require_edit(actor: User, s: Schedule) -> None:
    if not can_edit(actor, s):
        raise Forbidden("본인이 담당이거나 만든 일정만 고칠 수 있습니다.")


def get_or_404(db: Session, schedule_id: int) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if s is None or s.is_deleted:
        raise NotFound("일정을 찾을 수 없습니다.")
    return s


def _check_version(s: Schedule, expected: int) -> None:
    if s.version_no != expected:
        raise VersionConflict(
            "다른 사용자가 이 일정을 먼저 바꿨습니다. 최신 내용을 확인한 뒤 다시 시도하십시오.",
            detail={"expected_version": expected, "current_version_no": s.version_no,
                    "current": _snapshot(s)})


def _check_user(db: Session, user_id: int | None) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("담당자를 찾을 수 없거나 비활성 계정입니다.")


def _check_company(db: Session, company_id: int | None) -> None:
    if company_id is not None and db.get(Company, company_id) is None:
        raise ValidationFailed("관계사를 찾을 수 없습니다.")


def normalize_times(start: datetime, end: datetime | None, all_day: bool) -> tuple[datetime, datetime]:
    start = _aware(start)
    if all_day:
        days = 1
        if end is not None:
            end = _aware(end)
            days = (end.date() - start.date()).days + (0 if end.time() == time.min else 1)
        start, end = recurrence.whole_days(start, max(1, days))
    else:
        end = _aware(end) if end is not None else start + DEFAULT_LENGTH
        if end <= start:
            raise ValidationFailed("끝나는 시각이 시작 시각보다 늦어야 합니다.", detail={"field": "end_at"})
    if end - start > MAX_LENGTH:
        raise ValidationFailed("일정 하나는 31일을 넘을 수 없습니다. 길게 이어지는 일은 반복 일정으로 만드십시오.",
                               detail={"field": "end_at"})
    return start, end


def _notify_owner(db: Session, s: Schedule, actor: User) -> None:
    if s.owner_id and s.owner_id != actor.id:
        when = _aware(s.start_at).strftime("%m/%d") if s.is_all_day else _aware(s.start_at).strftime("%m/%d %H:%M")
        notification_service.notify(
            db, user_id=s.owner_id, type_=notification_service.T_SCHEDULE_ASSIGNED,
            title=f"일정이 배정되었습니다: {s.title}", body=f"{actor.display_name} 님이 배정 · {when}",
            link_type="SCHEDULE", link_id=s.id, dedup_key=f"schedule-assign:{s.id}")


# --------------------------------------------------------------------------- 만들기 · 고치기

def create(db: Session, actor: User, data: dict[str, Any], ctx: RequestContext | None = None) -> Schedule:
    handover = task = None
    if data.get("handover_id") is not None:
        handover = db.get(Handover, data["handover_id"])
        if handover is None or handover.is_deleted:
            raise ValidationFailed("연결할 인수인계를 찾을 수 없습니다.")
        from app.services import group_service
        if not group_service.can_see(db, handover, actor):
            raise ValidationFailed("연결할 인수인계를 찾을 수 없습니다.")
    if data.get("task_id") is not None:
        task = db.get(Task, data["task_id"])
        if task is None or task.is_deleted:
            raise ValidationFailed("연결할 할일을 찾을 수 없습니다.")

    title = (data.get("title") or "").strip() or (task.title if task else handover.title if handover else "")
    if not title:
        raise ValidationFailed("제목을 입력하십시오.", detail={"field": "title"})
    company_id = (data.get("company_id") or (task.company_id if task else None)
                  or (handover.company_id if handover else None))
    owner_id = data.get("owner_id") or actor.id
    _check_company(db, company_id)
    _check_user(db, owner_id)
    start, end = normalize_times(data["start_at"], data.get("end_at"), data.get("is_all_day", False))

    s = Schedule(
        title=title[:300], description=data.get("description"),
        event_type=data.get("event_type") or "GENERAL",
        start_at=start, end_at=end, is_all_day=bool(data.get("is_all_day")),
        company_id=company_id, handover_id=handover.id if handover else None,
        task_id=task.id if task else None, owner_id=owner_id,
        recurrence_rule=recurrence.normalize(data.get("recurrence_rule")),
        color=data.get("color"), created_by=actor.id, version_no=1,
    )
    db.add(s)
    db.flush()
    db.refresh(s)
    _notify_owner(db, s, actor)
    record(db, action=actions.CALENDAR_CREATE, ctx=ctx, user=actor, resource_type="SCHEDULE",
           resource_id=s.id, after={**_snapshot(s), "handover_id": s.handover_id, "task_id": s.task_id})
    return s


def update(db: Session, actor: User, schedule_id: int, expected_version: int,
           changes: dict[str, Any], ctx: RequestContext | None = None) -> Schedule:
    s = get_or_404(db, schedule_id)
    _require_edit(actor, s)
    _check_version(s, expected_version)
    before = _snapshot(s)
    old_owner = s.owner_id

    if "owner_id" in changes:
        _check_user(db, changes["owner_id"])
    if "company_id" in changes:
        _check_company(db, changes["company_id"])

    if {"start_at", "end_at", "is_all_day"} & changes.keys():
        all_day = changes.get("is_all_day", s.is_all_day)
        start = changes.get("start_at") or s.start_at
        if "end_at" in changes:
            end = changes["end_at"]
        elif "start_at" in changes and all_day == s.is_all_day:
            end = _aware(start) + (s.end_at - s.start_at)       # 시작만 옮기면 길이 유지
        elif all_day != s.is_all_day:
            end = None                                          # 종일 ↔ 시간 전환은 기본 길이로
        else:
            end = s.end_at
        s.start_at, s.end_at = normalize_times(start, end, all_day)
        s.is_all_day = all_day
    if "recurrence_rule" in changes:
        s.recurrence_rule = recurrence.normalize(changes["recurrence_rule"])
    for key in ("title", "description", "event_type", "company_id", "owner_id", "color"):
        if key in changes:
            value = changes[key]
            setattr(s, key, value.strip() if key == "title" else value)

    after = _snapshot(s)
    changed = [k for k in TRACKED if before[k] != after[k]]
    if not changed:
        return s
    s.version_no += 1
    db.flush()
    if s.owner_id != old_owner:
        _notify_owner(db, s, actor)
    record(db, action=actions.CALENDAR_UPDATE, ctx=ctx, user=actor, resource_type="SCHEDULE",
           resource_id=s.id, before={k: before[k] for k in changed},
           after={k: after[k] for k in changed})
    return s


def move(db: Session, actor: User, schedule_id: int, expected_version: int, start_at: datetime,
         end_at: datetime | None, ctx: RequestContext | None = None) -> Schedule:
    """달력 끌어놓기(FR-E-04). 끝을 주지 않으면 길이를 유지한다. 감사 기록 필수."""
    s = get_or_404(db, schedule_id)
    _require_edit(actor, s)
    _check_version(s, expected_version)
    before = {"start_at": _jsonable(s.start_at), "end_at": _jsonable(s.end_at)}
    if s.is_all_day:
        days = max(1, round((s.end_at - s.start_at) / timedelta(days=1)))
        s.start_at, s.end_at = normalize_times(start_at, end_at, True) if end_at else \
            recurrence.whole_days(_aware(start_at), days)
    else:
        start = _aware(start_at)
        s.start_at, s.end_at = normalize_times(start, end_at or start + (s.end_at - s.start_at), False)
    after = {"start_at": _jsonable(s.start_at), "end_at": _jsonable(s.end_at)}
    if after == before:
        return s
    s.version_no += 1
    db.flush()
    record(db, action=actions.CALENDAR_UPDATE, ctx=ctx, user=actor, resource_type="SCHEDULE",
           resource_id=s.id, before=before, after={**after, "via": "drag"})
    return s


def delete(db: Session, actor: User, schedule_id: int, reason: str | None,
           ctx: RequestContext | None = None) -> None:
    s = get_or_404(db, schedule_id)
    _require_edit(actor, s)
    s.is_deleted, s.deleted_at, s.deleted_by = True, now(), actor.id
    s.version_no += 1
    db.flush()
    record(db, action=actions.CALENDAR_DELETE, ctx=ctx, user=actor, resource_type="SCHEDULE",
           resource_id=s.id, before=_snapshot(s), after={"reason": reason})


# --------------------------------------------------------------------------- 조회

def check_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = _aware(start), _aware(end)
    if end <= start:
        raise ValidationFailed("기간의 끝이 시작보다 늦어야 합니다.")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ValidationFailed(f"한 번에 볼 수 있는 기간은 {MAX_RANGE_DAYS}일까지입니다.")
    return start, end


def occurrences_in(db: Session, start: datetime, end: datetime, *, owner_id: int | None = None,
                   company_id: int | None = None,
                   schedule_id: int | None = None) -> list[tuple[Schedule, datetime, datetime]]:
    """기간과 겹치는 회차. 반복 일정은 시작이 기간 끝보다 앞이면 후보로 두고 펼쳐서 거른다."""
    stmt = select(Schedule).where(
        Schedule.is_deleted == false(), Schedule.start_at < end,
        or_(Schedule.recurrence_rule.is_not(None), Schedule.end_at > start))
    if owner_id is not None:
        stmt = stmt.where(Schedule.owner_id == owner_id)
    if company_id is not None:
        stmt = stmt.where(Schedule.company_id == company_id)
    if schedule_id is not None:
        stmt = stmt.where(Schedule.id == schedule_id)
    found = []
    for s in db.scalars(stmt):
        for a, b in recurrence.occurrences(s.recurrence_rule, _aware(s.start_at), _aware(s.end_at), start, end):
            found.append((s, a, b))
    found.sort(key=lambda r: (r[1], r[0].id))
    return found


def calendar(db: Session, actor: User, start: datetime, end: datetime, layers: set[str],
             mine: bool = False) -> dict[str, Any]:
    """일정 + 할일 마감 + 인수인계 수행일을 한 달력에(UI_STRUCTURE §6 레이어)."""
    start, end = check_range(start, end)
    first_day = start.date()
    last_day = (end - timedelta(microseconds=1)).date()
    t0 = today()
    events: list[dict[str, Any]] = []

    if "schedule" in layers:
        for s, a, b in occurrences_in(db, start, end, owner_id=actor.id if mine else None):
            events.append({
                "key": f"S{s.id}@{a.isoformat()}", "kind": "SCHEDULE", "id": s.id, "title": s.title,
                "start": a, "end": b, "all_day": s.is_all_day, "event_type": s.event_type,
                "color": s.color, "company": s.company.name if s.company else None,
                "recurring": bool(s.recurrence_rule),
                "owner": s.owner.display_name if s.owner else None,
                "can_move": can_edit(actor, s) and not s.recurrence_rule,
                "version_no": s.version_no,
            })

    if "task" in layers:
        stmt = select(Task).where(Task.is_deleted == false(), Task.status != TASK_CANCELED,
                                  Task.due_date >= first_day, Task.due_date <= last_day)
        if mine:
            stmt = stmt.where(Task.assignee_id == actor.id)
        for t in db.scalars(stmt.order_by(Task.due_date, Task.id)):
            events.append({
                "key": f"T{t.id}", "kind": "TASK", "id": t.id, "title": t.title, "day": t.due_date,
                "all_day": True, "status": t.status, "company": t.company.name if t.company else None,
                "is_done": t.status == TASK_DONE,
                "is_overdue": t.due_date < t0 and t.status not in TASK_CLOSED_STATES,
                "owner": t.assignee.display_name if t.assignee else None,
            })

    if "handover" in layers:
        from app.services import group_service
        stmt = (select(Handover, HandoverStatus.category)
                .join(HandoverStatus, HandoverStatus.code == Handover.status_code)
                .where(Handover.is_deleted == false(), Handover.work_date >= first_day,
                       Handover.work_date <= last_day,
                       group_service.visible_clause(db, actor.id)))
        if mine:
            stmt = stmt.where(Handover.assignee_id == actor.id)
        for h, category in db.execute(stmt.order_by(Handover.work_date, Handover.id)):
            closed = category == "CLOSED"
            events.append({
                "key": f"H{h.id}", "kind": "HANDOVER", "id": h.id, "title": h.title, "day": h.work_date,
                "all_day": True, "status": h.status.name if h.status else h.status_code,
                "company": h.company.name if h.company else None, "is_done": closed,
                "is_overdue": h.work_date < t0 and not closed,
                "owner": h.assignee.display_name if h.assignee else None,
            })

    truncated = len(events) > MAX_EVENTS
    return {"start": start, "end": end, "events": events[:MAX_EVENTS], "truncated": truncated}


def for_handover(db: Session, handover_id: int) -> list[Schedule]:
    return list(db.scalars(select(Schedule).where(Schedule.handover_id == handover_id,
                                                  Schedule.is_deleted == false())
                           .order_by(Schedule.start_at, Schedule.id)))


def for_task(db: Session, task_id: int) -> list[Schedule]:
    return list(db.scalars(select(Schedule).where(Schedule.task_id == task_id,
                                                  Schedule.is_deleted == false())
                           .order_by(Schedule.start_at, Schedule.id)))


def count_for_handover(db: Session, handover_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Schedule)
                     .where(Schedule.handover_id == handover_id, Schedule.is_deleted == false())) or 0


def next_occurrences(db: Session, owner_id: int, start: datetime, end: datetime) -> list[tuple[Schedule, datetime, datetime]]:
    """내 업무용 — 일정마다 기간 안의 가장 가까운 회차 하나(매일 반복이 목록을 채우지 않게)."""
    seen: set[int] = set()
    picked = []
    for s, a, b in occurrences_in(db, start, end, owner_id=owner_id):
        if s.id not in seen:
            seen.add(s.id)
            picked.append((s, a, b))
    return picked


# --------------------------------------------------------------------------- 내 알림

#: 화면이 내놓는 선택지. '직접'은 1~10080분(7일) 사이의 아무 값.
REMINDER_CHOICES = (None, 0, 10, 30)
MAX_REMINDER_MIN = 7 * 24 * 60


def my_reminder(db: Session, schedule_id: int, user_id: int) -> int | None:
    row = db.scalar(select(ScheduleReminder).where(
        ScheduleReminder.schedule_id == schedule_id, ScheduleReminder.user_id == user_id))
    return row.minutes_before if row else None


def set_reminder(db: Session, actor: User, schedule_id: int,
                 minutes_before: int | None) -> int | None:
    """내 알림을 정한다. None 이면 끄기(행을 지운다 — 끈 것과 설정이 없는 것은 같다)."""
    get_or_404(db, schedule_id)
    if minutes_before is not None:
        if minutes_before < 0 or minutes_before > MAX_REMINDER_MIN:
            raise ValidationFailed(f"알림은 0분(시작) ~ {MAX_REMINDER_MIN}분 전 사이로 넣으십시오.",
                                   detail={"field": "minutes_before"})
    row = db.scalar(select(ScheduleReminder).where(
        ScheduleReminder.schedule_id == schedule_id, ScheduleReminder.user_id == actor.id))
    if minutes_before is None:
        if row is not None:
            db.delete(row)
            db.flush()
        return None
    if row is None:
        row = ScheduleReminder(schedule_id=schedule_id, user_id=actor.id)
        db.add(row)
    row.minutes_before = int(minutes_before)
    db.flush()
    return row.minutes_before


def mine_upcoming(db: Session, actor: User, *, days: int = 7,
                  per_series: int = 3) -> list[dict[str, Any]]:
    """'내 일정' — 오늘부터 N일, 반복 일정은 **앞의 몇 회차만**.

    매일 반복하는 점검이 하나 있으면 7일치가 7줄이 되어 다른 일정을 밀어낸다.
    그래서 한 일정(series)당 per_series 회차까지만 보여 주고, 더 있으면 몇 번 더 있는지 센다.
    """
    start = now()
    end = start + timedelta(days=days)
    counts: dict[int, int] = {}
    rows: list[dict[str, Any]] = []
    for s, a, b in occurrences_in(db, start, end, owner_id=actor.id):
        counts[s.id] = counts.get(s.id, 0) + 1
        if counts[s.id] > per_series:
            continue
        rows.append({
            "id": s.id, "title": s.title, "event_type": s.event_type,
            "start_at": a, "end_at": b, "is_all_day": s.is_all_day,
            "company": s.company.name if s.company else None,
            "handover_id": s.handover_id, "task_id": s.task_id,
            "recurrence_rule": s.recurrence_rule,
            "reminder_minutes": my_reminder(db, s.id, actor.id),
            "occurrence_no": counts[s.id],
        })
    rows.sort(key=lambda r: r["start_at"])
    for row in rows:
        total = counts[row["id"]]
        row["more_occurrences"] = max(0, total - per_series) if row["occurrence_no"] == 1 else 0
    return rows


def to_out(actor: User, s: Schedule) -> dict[str, Any]:
    series_end = None
    if s.recurrence_rule:
        series_end = recurrence.last_occurrence_end(s.recurrence_rule, _aware(s.start_at), _aware(s.end_at))
    link = lambda obj: {"id": obj.id, "title": obj.title, "is_deleted": obj.is_deleted} if obj else None  # noqa: E731
    return {
        "id": s.id, "title": s.title, "description": s.description, "event_type": s.event_type,
        "start_at": _aware(s.start_at), "end_at": _aware(s.end_at), "is_all_day": s.is_all_day,
        "company": s.company, "handover": link(s.handover), "task": link(s.task),
        "owner": s.owner, "creator": s.creator,
        "recurrence_rule": s.recurrence_rule, "recurrence_text": recurrence.describe(s.recurrence_rule),
        "series_end": series_end, "color": s.color, "version_no": s.version_no,
        "can_edit": can_edit(actor, s), "created_at": s.created_at, "updated_at": s.updated_at,
    }
