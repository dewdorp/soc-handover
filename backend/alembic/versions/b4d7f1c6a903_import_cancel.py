"""가져오기 중단 — excel_import_jobs.cancel_requested

반영 중에 사람이 멈출 수 있어야 한다. 행 중간이 아니라 배치 경계에서 멈춘다.

Revision ID: b4d7f1c6a903
Revises: a7c3e5b19d84
Create Date: 2026-11-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7f1c6a903"
down_revision: Union[str, None] = "a7c3e5b19d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("excel_import_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("excel_import_jobs", schema=None) as batch_op:
        batch_op.drop_column("cancel_requested")
