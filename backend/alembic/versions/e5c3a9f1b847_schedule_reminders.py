"""일정 알림 — schedule_reminders (사람마다 따로)

일정은 여러 사람이 보지만 알림은 개인 설정이다. 일정 테이블에 컬럼으로 넣으면
한 사람이 끈 것이 모두에게 적용된다.

minutes_before: NULL=끄기 · 0=시작할 때 · 10/30=N분 전 · 그 밖=직접 넣은 분

Revision ID: e5c3a9f1b847
Revises: d4b1c7e8a206
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c3a9f1b847"
down_revision: Union[str, None] = "d4b1c7e8a206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schedule_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("minutes_before", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("schedule_id", "user_id", name="uq_sched_reminder"),
    )
    op.create_index("ix_sched_reminder_user", "schedule_reminders", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sched_reminder_user", table_name="schedule_reminders")
    op.drop_table("schedule_reminders")
