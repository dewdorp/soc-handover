"""인수자 여러 명 — shift_handovers.to_user_id 를 shift_handover_recipients 로

현장 요청: 한 번의 인계를 다음 근무자 여러 명에게 동시에 넘긴다(2인 교대·인수인계 참관).
컬럼 하나로는 한 명밖에 담지 못해 표로 옮긴다. 기존 인계 기록은 인수자 1명짜리로 그대로 옮겨진다.

Revision ID: d5c8b2a6f931
Revises: b3f1a7c9d240
Create Date: 2026-09-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5c8b2a6f931"
down_revision: Union[str, None] = "b3f1a7c9d240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_handover_recipients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["shift_handovers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_shr_session_user"),
    )
    with op.batch_alter_table("shift_handover_recipients", schema=None) as batch_op:
        batch_op.create_index("ix_shr_user", ["user_id", "session_id"], unique=False)

    # 지금까지의 인계는 인수자 1명 — 그대로 옮긴다(옮기기 전에는 컬럼을 지우지 않는다).
    op.execute(
        "INSERT INTO shift_handover_recipients (session_id, user_id, display_order) "
        "SELECT id, to_user_id, 0 FROM shift_handovers WHERE to_user_id IS NOT NULL"
    )

    with op.batch_alter_table("shift_handovers", schema=None) as batch_op:
        batch_op.drop_index("ix_sh_to_user")
        batch_op.drop_column("to_user_id")


def downgrade() -> None:
    with op.batch_alter_table("shift_handovers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("to_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_sh_to_user", "users", ["to_user_id"], ["id"])
        batch_op.create_index("ix_sh_to_user", ["to_user_id", "status"], unique=False)

    # 컬럼은 한 명만 담는다 — 먼저 고른 사람만 남고 나머지 인수자는 사라진다.
    op.execute(
        "UPDATE shift_handovers SET to_user_id = ("
        " SELECT r.user_id FROM shift_handover_recipients r"
        " WHERE r.session_id = shift_handovers.id"
        " ORDER BY r.display_order, r.id LIMIT 1)"
    )

    with op.batch_alter_table("shift_handover_recipients", schema=None) as batch_op:
        batch_op.drop_index("ix_shr_user")
    op.drop_table("shift_handover_recipients")
