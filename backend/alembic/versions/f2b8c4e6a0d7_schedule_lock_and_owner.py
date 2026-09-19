"""일정(schedules): 낙관적 잠금 · 만든 사람 · 삭제 기록

- version_no: 달력에서 두 사람이 같은 일정을 동시에 옮겨도 한쪽이 조용히 덮어쓰지 않게(§26).
- created_by: 담당(owner)을 다른 사람으로 정해 만들어도 만든 사람이 고칠 수 있게.
- deleted_at / deleted_by: 삭제는 표시만 하고 누가 언제 지웠는지 남긴다.

Revision ID: f2b8c4e6a0d7
Revises: e7a3d9c5b1f4
Create Date: 2026-09-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b8c4e6a0d7"
down_revision: Union[str, None] = "e7a3d9c5b1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("schedules", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_sched_created_by", "users", ["created_by"], ["id"])
        batch_op.create_foreign_key("fk_sched_deleted_by", "users", ["deleted_by"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("schedules", schema=None) as batch_op:
        batch_op.drop_constraint("fk_sched_deleted_by", type_="foreignkey")
        batch_op.drop_constraint("fk_sched_created_by", type_="foreignkey")
        batch_op.drop_column("deleted_by")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("created_by")
        batch_op.drop_column("version_no")
