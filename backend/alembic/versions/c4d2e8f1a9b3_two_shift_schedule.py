"""교대를 2교대로 전환 — 주간 09:00~18:00 · 야간 18:00~다음날 09:00

운영 확인(ASSUMPTIONS G-01): 실제 교대는 3교대가 아니라 주간·야간 2교대다.

- DAY(주간)·NIGHT(야간)의 시간을 바꾼다.
- SWING(오후)은 **지우지 않고 비활성화**한다. 과거 인계 기록(shift_handovers)이
  참조하고 있을 수 있고, 지우면 그 기록이 어느 교대였는지 알 수 없게 된다.
- 행이 없으면(새 설치에서 기준데이터 생성 전) 아무 것도 하지 않는다.
  새 설치는 bootstrap_service 의 기본값(이미 2교대)으로 만들어진다.

Revision ID: c4d2e8f1a9b3
Revises: b7e3c9a41f20
Create Date: 2026-09-19
"""
from __future__ import annotations

from datetime import time
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d2e8f1a9b3"
down_revision: Union[str, None] = "b7e3c9a41f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

shifts = sa.table(
    "shifts",
    sa.column("code", sa.String), sa.column("name", sa.String),
    sa.column("start_time", sa.Time), sa.column("end_time", sa.Time),
    sa.column("crosses_midnight", sa.Boolean), sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.SmallInteger),
)


def _set(code: str, **values) -> None:
    op.execute(shifts.update().where(shifts.c.code == code).values(**values))


def upgrade() -> None:
    _set("DAY", name="주간", start_time=time(9, 0), end_time=time(18, 0),
         crosses_midnight=False, is_active=True, sort_order=10)
    _set("NIGHT", name="야간", start_time=time(18, 0), end_time=time(9, 0),
         crosses_midnight=True, is_active=True, sort_order=20)
    _set("SWING", is_active=False, sort_order=90)


def downgrade() -> None:
    _set("DAY", name="주간", start_time=time(8, 0), end_time=time(16, 0),
         crosses_midnight=False, is_active=True, sort_order=10)
    _set("SWING", name="오후", start_time=time(16, 0), end_time=time(0, 0),
         crosses_midnight=True, is_active=True, sort_order=20)
    _set("NIGHT", name="야간", start_time=time(0, 0), end_time=time(8, 0),
         crosses_midnight=False, is_active=True, sort_order=30)
