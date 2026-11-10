"""일정(Calendar Event). Handover/Task 와 상호 연결된다(§42~§43)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TZDateTime

EVENT_TYPES = ("GENERAL", "WORK_PLANNED", "INSPECTION", "MEETING", "SECURITY_WORK", "RECURRING")


class Schedule(Base, TimestampMixin):
    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_sched_range", "start_at", "end_at"),
        Index("ix_sched_owner", "owner_id", "start_at"),
        Index("ix_sched_handover", "handover_id"),
        Index("ix_sched_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, default="GENERAL")
    start_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    handover_id: Mapped[int | None] = mapped_column(ForeignKey("handovers.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recurrence_rule: Mapped[str | None] = mapped_column(String(200))
    color: Mapped[str | None] = mapped_column(String(7))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 낙관적 잠금(§26) — 수정·달력 이동마다 1씩 오른다.
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    company = relationship("Company", lazy="joined")
    owner = relationship("User", foreign_keys=[owner_id], lazy="joined")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    handover = relationship("Handover", lazy="joined")
    task = relationship("Task", lazy="joined")


class ScheduleReminder(Base, TimestampMixin):
    """'이 일정을 나에게 언제 알려 줄까' — **사람마다 따로**.

    일정은 여러 사람이 보는 것이지만 알림은 개인 설정이다. 일정에 컬럼으로 넣으면
    한 사람이 끈 것이 모두에게 적용된다.

    minutes_before 의 뜻
      None  알리지 않는다(끄기)
      0     시작할 때
      10/30 10분 전 · 30분 전
      그 밖 직접 넣은 분
    """

    __tablename__ = "schedule_reminders"
    __table_args__ = (
        UniqueConstraint("schedule_id", "user_id", name="uq_sched_reminder"),
        Index("ix_sched_reminder_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"),
                                             nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         nullable=False)
    minutes_before: Mapped[int | None] = mapped_column(Integer)


class ScheduleCompletion(Base, TimestampMixin):
    """정기 점검의 **회차별** 완료 표시.

    '점검' 종류의 반복 일정 하나가 매일·매주 돌면서 회차를 만든다. 완료를 일정에
    컬럼으로 넣으면 한 번 끝낸 뒤 다음 회차가 이미 끝난 것으로 보인다. 그래서 회차
    (그 날)마다 한 줄 남긴다. 담당자가 비어 있는 점검은 근무자 누구나 끝낼 수 있고,
    누가 끝냈는지는 여기 남는다.
    """

    __tablename__ = "schedule_completions"
    __table_args__ = (
        UniqueConstraint("schedule_id", "occurrence_date", name="uq_sched_completion"),
        Index("ix_sched_completion_date", "occurrence_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    #: 회차 = 그 날(KST). 하루 두 번 도는 점검은 한 회차로 본다.
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    done_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    note: Mapped[str | None] = mapped_column(String(300))
