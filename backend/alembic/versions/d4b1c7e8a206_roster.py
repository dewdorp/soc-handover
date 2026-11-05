"""근무표 — roster_teams · roster_members · roster_overrides

4조 2교대는 16일 주기로 되풀이되므로 날짜별 행을 깔지 않는다. 조마다 주기 위치만 적고,
달라지는 것(대근 · 맞교환 · 결원)만 roster_overrides 에 예외로 쌓는다.

기본 4조(1~4조, 주기 위치 0·4·8·12)를 함께 넣는다 — 그래야 설치 직후에도 달력이 그려진다.
사람은 넣지 않는다(실제 명단은 현장에서 채운다).

Revision ID: d4b1c7e8a206
Revises: c8a2f4e7b015
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b1c7e8a206"
down_revision: Union[str, None] = "c8a2f4e7b015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEAMS = [("A", "1조", 0, 1), ("B", "2조", 4, 2), ("C", "3조", 8, 3), ("D", "4조", 12, 4)]


def upgrade() -> None:
    op.create_table(
        "roster_teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("phase_days", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_roster_team_code"),
    )
    op.create_index("ix_roster_team_active", "roster_teams", ["is_active", "sort_order"])

    op.create_table(
        "roster_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_leader", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["team_id"], ["roster_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_roster_member"),
    )
    op.create_index("ix_roster_member_user", "roster_members", ["user_id"])

    op.create_table(
        "roster_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("shift_code", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("off_user_id", sa.Integer(), nullable=False),
        sa.Column("on_user_id", sa.Integer(), nullable=True),
        sa.Column("pair_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_by", sa.Integer(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["off_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["on_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["canceled_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["pair_id"], ["roster_overrides.id"]),
    )
    op.create_index("ix_roster_ovr_date", "roster_overrides", ["work_date", "shift_code"])
    op.create_index("ix_roster_ovr_off", "roster_overrides", ["off_user_id", "work_date"])
    op.create_index("ix_roster_ovr_on", "roster_overrides", ["on_user_id", "work_date"])

    conn = op.get_bind()
    for code, name, phase, order in TEAMS:
        conn.execute(sa.text(
            "INSERT INTO roster_teams (code, name, phase_days, is_active, sort_order,"
            "                          created_at, updated_at) "
            "VALUES (:code, :name, :phase, :yes, :order, "
            "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"code": code, "name": name, "phase": phase, "yes": True, "order": order})


def downgrade() -> None:
    op.drop_index("ix_roster_ovr_on", table_name="roster_overrides")
    op.drop_index("ix_roster_ovr_off", table_name="roster_overrides")
    op.drop_index("ix_roster_ovr_date", table_name="roster_overrides")
    op.drop_table("roster_overrides")
    op.drop_index("ix_roster_member_user", table_name="roster_members")
    op.drop_table("roster_members")
    op.drop_index("ix_roster_team_active", table_name="roster_teams")
    op.drop_table("roster_teams")
