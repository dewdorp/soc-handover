"""할일(tasks)에 낙관적 잠금용 version_no 추가

인수인계와 같은 원칙(§26): 두 사람이 같은 할일을 동시에 고치면 나중 저장이 앞의 것을
조용히 덮어쓰지 않고 409 로 막는다. 보드에서 같은 카드를 동시에 옮길 때도 같다.

Revision ID: e7a3d9c5b1f4
Revises: c4d2e8f1a9b3
Create Date: 2026-09-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3d9c5b1f4"
down_revision: Union[str, None] = "c4d2e8f1a9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version_no", sa.Integer(), nullable=False,
                                      server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("version_no")
