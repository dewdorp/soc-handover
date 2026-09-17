"""일정(Calendar Event). Handover/Task 와 상호 연결된다(§42~§43)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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
