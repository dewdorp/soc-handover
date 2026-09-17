"""Task(실행 항목) / Checklist / Comment. Handover(사실)와 개념적으로 분리한다(§37)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, ForeignKey, Index, Integer, SmallInteger,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TZDateTime

TASK_TODO = "TODO"
TASK_IN_PROGRESS = "IN_PROGRESS"
TASK_WAITING = "WAITING"
TASK_DONE = "DONE"
TASK_CANCELED = "CANCELED"
TASK_CLOSED_STATES = (TASK_DONE, TASK_CANCELED)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_task_assignee", "assignee_id", "status", "due_date"),
        Index("ix_task_handover", "handover_id"),
        Index("ix_task_due", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int | None] = mapped_column(ForeignKey("handovers.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TASK_TODO)
    priority_code: Mapped[str] = mapped_column(ForeignKey("priorities.code"),
                                               nullable=False, default="NORMAL")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    board_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    checklists = relationship("TaskChecklist", cascade="all, delete-orphan",
                              order_by="TaskChecklist.sort_order", lazy="selectin")


class TaskChecklist(Base, TimestampMixin):
    __tablename__ = "task_checklists"
    __table_args__ = (Index("ix_checklist_task", "task_id", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"),
                                         nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class TaskComment(Base, TimestampMixin):
    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comment", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"),
                                         nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
