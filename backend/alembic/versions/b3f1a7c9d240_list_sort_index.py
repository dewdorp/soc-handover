"""목록 기본 정렬용 인덱스 (상단고정 → 등록일 → id)

목록 첫 페이지는 `is_pinned DESC, registered_date DESC, id DESC` 로 정렬한다(compiler.compile_order).
기존 인덱스는 이 순서를 덮지 못해(ix_ho_list 는 오름차순 · ix_ho_important 는 고정/중요 건만)
50만 건에서 전체를 정렬한 뒤 50건을 잘라 썼다 — 실측 첫 페이지 0.9초.

Revision ID: b3f1a7c9d240
Revises: a9d4f7c2e815
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b3f1a7c9d240"
down_revision: Union[str, None] = "a9d4f7c2e815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "ix_ho_list_sort"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {NAME} ON handovers "
        "(is_pinned DESC, registered_date DESC, id DESC) WHERE is_deleted = false"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {NAME}")
