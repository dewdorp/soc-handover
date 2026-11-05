"""할일 마감 알림(§66 TASK_DUE_SOON · TASK_OVERDUE) — 주기적으로 돈다.

- 마감 임박: 안 끝난 내 할일의 마감이 오늘 또는 내일.
- 지연: 마감이 지났는데 안 끝남.
- 할일마다 **하루 한 번**(dedup 키에 날짜) — 읽은 뒤에도 30분마다 다시 오지 않게 notify_once.
- 담당자가 없거나 비활성이면 보내지 않는다.

서버 안에서 threading 타이머로 돈다(REMINDER_INTERVAL_MIN, 0 이면 끔). 작업자가 여럿이어도 dedup 키가
같아 두 번 쌓이지 않는다(거의 같은 순간 경합은 드물게 두 건이 될 수 있다 — 알림이라 허용).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.core.time import KST, now
from app.models.task import TASK_CLOSED_STATES, Task
from app.models.user import User
from app.services import notification_service as ns

log = logging.getLogger("app.reminders")


def run(db: Session, at: datetime | None = None) -> dict[str, int]:
    today = (at or now()).astimezone(KST).date()
    tomorrow = today + timedelta(days=1)
    rows = db.execute(
        select(Task, User.is_active)
        .join(User, User.id == Task.assignee_id)
        .where(Task.is_deleted == false(), Task.status.notin_(TASK_CLOSED_STATES),
               Task.due_date.is_not(None), Task.due_date <= tomorrow)).all()
    sent = {"due_soon": 0, "overdue": 0}
    for task, active in rows:
        if not active:
            continue
        if task.due_date < today:
            days = (today - task.due_date).days
            made = ns.notify_once(db, user_id=task.assignee_id, type_=ns.T_TASK_OVERDUE,
                                  title=f"지연된 할일: {task.title}",
                                  body=f"마감 {task.due_date.isoformat()} · {days}일 지남",
                                  link_type="TASK", link_id=task.id,
                                  dedup_key=f"task-overdue:{task.id}:{today.isoformat()}")
            sent["overdue"] += made is not None
        else:
            when = "오늘" if task.due_date == today else "내일"
            made = ns.notify_once(db, user_id=task.assignee_id, type_=ns.T_TASK_DUE_SOON,
                                  title=f"마감 임박: {task.title}", body=f"{when} 마감",
                                  link_type="TASK", link_id=task.id,
                                  dedup_key=f"task-due:{task.id}:{today.isoformat()}")
            sent["due_soon"] += made is not None
    return sent


class ReminderLoop:
    """interval 분마다 run() — 첫 실행은 기동 1분 뒤(기동 직후 부하를 피한다)."""

    def __init__(self, interval_min: int):
        self.interval = interval_min * 60
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="reminders", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        from app.core.db import SessionLocal

        if self._stop.wait(60):
            return
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    sent = run(db)
                    # 일정 알림은 할일 알림과 같은 주기로 돈다(작업 스레드를 둘로 늘리지 않는다).
                    sent["schedule"] = run_schedule_reminders(db)
                    db.commit()
                if any(sent.values()):
                    log.info("알림: 마감 임박 %s건 · 지연 %s건 · 일정 %s건",
                             sent["due_soon"], sent["overdue"], sent["schedule"])
            except Exception:  # pragma: no cover - 알림 실패가 서버를 멈추면 안 된다
                log.warning("마감 알림 작업 실패", exc_info=True)
            if self._stop.wait(self.interval):
                return


# --------------------------------------------------------------------------- 일정 알림

#: 서버가 멈춰 있었거나 작업 간격이 길어 때를 놓친 경우, 이 시간까지는 늦게라도 보낸다.
LATE_GRACE = timedelta(hours=2)


def run_schedule_reminders(db: Session, at: datetime | None = None) -> int:
    """사람이 일정마다 정해 둔 '내 알림'을 보낸다(§6).

    알림 하나가 가야 할 순간은 '회차 시작 시각 − 설정 분'이다. 작업이 몇 분마다 돌기
    때문에 그 순간을 정확히 집지 못한다. 그래서 **이미 지난 알림**을 찾아 보내고,
    회차마다 dedup 키를 달아 두 번 가지 않게 한다. 너무 늦은 것(LATE_GRACE 초과)은
    보내지 않는다 — 지난 일을 뒤늦게 알리면 지금 일로 착각한다.
    """
    from app.models.schedule import Schedule, ScheduleReminder
    from app.services import schedule_service

    stamp = (at or now()).astimezone(KST)
    rows = db.execute(
        select(ScheduleReminder, Schedule, User.is_active)
        .join(Schedule, Schedule.id == ScheduleReminder.schedule_id)
        .join(User, User.id == ScheduleReminder.user_id)
        .where(ScheduleReminder.minutes_before.is_not(None),
               Schedule.is_deleted == false())).all()

    sent = 0
    for reminder, schedule, active in rows:
        if not active:
            continue
        lead = timedelta(minutes=reminder.minutes_before or 0)
        # 알림을 보낼 때가 지난 회차 중 가장 나중 것 하나만 본다.
        window_from = stamp - LATE_GRACE
        candidates = schedule_service.occurrences_in(
            db, window_from, stamp + lead, owner_id=None, schedule_id=schedule.id)
        for _s, start, _end in candidates:
            fire_at = start - lead
            if not (window_from <= fire_at <= stamp):
                continue
            when = start.astimezone(KST)
            lead_text = "지금 시작" if not reminder.minutes_before else f"{reminder.minutes_before}분 뒤"
            made = ns.notify_once(
                db, user_id=reminder.user_id, type_=ns.T_SCHEDULE_REMINDER,
                title=f"일정 알림: {schedule.title}",
                body=f"{when:%m/%d %H:%M} · {lead_text}",
                link_type="SCHEDULE", link_id=schedule.id,
                dedup_key=f"sched-remind:{schedule.id}:{reminder.user_id}:{start.isoformat()}")
            sent += made is not None
    return sent
