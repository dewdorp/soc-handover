"""Basket 에서 직접 뺀 건 기록 — shift_carry_skips

Basket 은 열어 둔 뒤에 받은 인계도 반영해야 해서 열 때마다 후보를 다시 채운다.
그러면 사람이 일부러 뺀 건이 되살아나므로, 뺀 사실을 남겨 두고 다음 발송 때 지운다.

Revision ID: a7c3e5b19d84
Revises: f31b8d42a670
Create Date: 2026-11-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e5b19d84"
down_revision: Union[str, None] = "f31b8d42a670"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_carry_skips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("handover_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "handover_id", name="uq_skip_user_handover"),
    )
    with op.batch_alter_table("shift_carry_skips", schema=None) as batch_op:
        batch_op.create_index("ix_skip_user", ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("shift_carry_skips", schema=None) as batch_op:
        batch_op.drop_index("ix_skip_user")
    op.drop_table("shift_carry_skips")
