"""Excel Import 진행 단계 · 결과 요약 · 행 경고 컬럼 추가

- excel_import_jobs.phase   : RUNNING 중 무엇을 하는지(STAGE/PREPARE/COMMIT/ROLLBACK),
                              실패 시 어디서 멈췄는지 남긴다.
- excel_import_jobs.report  : 완료/롤백 결과 요약(JSON).
- excel_import_rows.warnings: 막지는 않지만 사용자가 알아야 하는 것(JSON 배열).

SQLite 는 ALTER TABLE ADD COLUMN 을 지원하므로 batch 모드 없이 추가한다.

Revision ID: b7e3c9a41f20
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e3c9a41f20"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("excel_import_jobs", sa.Column("phase", sa.String(length=20), nullable=True))
    op.add_column("excel_import_jobs", sa.Column("report", _JSON, nullable=True))
    op.add_column("excel_import_rows", sa.Column("warnings", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("excel_import_rows") as batch:
        batch.drop_column("warnings")
    with op.batch_alter_table("excel_import_jobs") as batch:
        batch.drop_column("report")
        batch.drop_column("phase")
