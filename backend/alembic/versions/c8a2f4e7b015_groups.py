"""열람 그룹 — groups · user_groups · handover_groups · handovers.visibility

이관 방침(§3)
  이미 쌓인 자료를 '전체 공개'로 바꾸지 않는다. 대신 **'미분류'라는 그룹 하나**를 만들어
  기존 업무 전부를 그 그룹에 넣고, 기존 사용자 전부를 그 그룹의 구성원으로 넣는다.

  · 지금 보이는 것이 그대로 보인다 — 운영이 끊기지 않는다.
  · 그러나 자료는 '모두에게 열린 것'이 아니라 '한 그룹에 속한 것'이 된다. 관리자가
    관계사별로 실제 그룹으로 옮기면(POST /groups/unclassified/move) 그 순간부터 좁아진다.
  · 앞으로 그룹에 넣지 않고 만든 계정은 '미분류' 자료를 보지 못한다(새 사람에게
    과거 자료가 자동으로 열리지 않는다).

Revision ID: c8a2f4e7b015
Revises: b4d7f1c6a903
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8a2f4e7b015"
down_revision: Union[str, None] = "b4d7f1c6a903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNCLASSIFIED_NAME = "미분류"
UNCLASSIFIED_DESC = "그룹이 정해지지 않은 자료. 관리자가 옮기기 전까지 이 그룹만 본다."


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=30), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_groups_code"),
        sa.UniqueConstraint("name", name="uq_groups_name"),
    )
    op.create_index("ix_groups_active", "groups", ["is_active", "sort_order"])

    op.create_table(
        "user_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_user_group"),
    )
    op.create_index("ix_ug_user", "user_groups", ["user_id"])
    op.create_index("ix_ug_group", "user_groups", ["group_id"])

    op.create_table(
        "handover_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handover_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("handover_id", "group_id", name="uq_handover_group"),
    )
    op.create_index("ix_hg_group", "handover_groups", ["group_id"])

    with op.batch_alter_table("handovers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("visibility", sa.String(length=20), nullable=False,
                                      server_default="GROUPS"))

    # ----------------------------------------------------------------- 이관
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO groups (code, name, description, is_active, sort_order,"
        "                    created_at, updated_at) "
        "VALUES ('UNCLASSIFIED', :name, :desc, :yes, 999, "
        "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ), {"name": UNCLASSIFIED_NAME, "desc": UNCLASSIFIED_DESC, "yes": True})
    gid = conn.execute(sa.text(
        "SELECT id FROM groups WHERE code = 'UNCLASSIFIED'")).scalar_one()

    # 기존 사용자 전부를 구성원으로 — 지금 보이는 것이 그대로 보여야 한다.
    conn.execute(sa.text(
        "INSERT INTO user_groups (user_id, group_id, is_default, created_at, updated_at) "
        "SELECT id, :gid, :yes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM users"
    ), {"gid": gid, "yes": True})

    # 기존 업무 전부를 '미분류' 그룹에 — 삭제된 것까지(복구하면 다시 보여야 한다).
    conn.execute(sa.text(
        "INSERT INTO handover_groups (handover_id, group_id) "
        "SELECT id, :gid FROM handovers"
    ), {"gid": gid})


def downgrade() -> None:
    with op.batch_alter_table("handovers", schema=None) as batch_op:
        batch_op.drop_column("visibility")
    op.drop_index("ix_hg_group", table_name="handover_groups")
    op.drop_table("handover_groups")
    op.drop_index("ix_ug_group", table_name="user_groups")
    op.drop_index("ix_ug_user", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index("ix_groups_active", table_name="groups")
    op.drop_table("groups")
