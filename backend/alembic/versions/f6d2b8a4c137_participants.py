"""복수 담당 · 필수 인수자 · 참고 전파 — handover_participants + 분석 의뢰 흐름

왜 assignee_id 하나로는 모자란가: 한 건에 '손대는 사람 / 꼭 확인해야 하는 사람 / 알고만
있으면 되는 사람'이 섞인다. 구분하지 않으면 참고로 보낸 사람까지 미확인으로 잡힌다.

기존 자료 이관: handovers.assignee_id 가 있는 건은 그 사람을 **대표 담당(OWNER)** 으로
넣는다. 지금과 똑같이 보이고, 앞으로 공동 담당·필수 인수자를 더할 자리가 생긴다.

분석 의뢰 흐름은 handovers 에 상태 네 칸으로 붙인다(NONE → REQUESTED → ACCEPTED →
ANSWERED). 별도 테이블을 두지 않은 이유: 한 업무에 흐름이 하나뿐이고, 목록에서 '의뢰
중인 건'을 거르려면 같은 행에 있어야 한다.

Revision ID: f6d2b8a4c137
Revises: e5c3a9f1b847
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6d2b8a4c137"
down_revision: Union[str, None] = "e5c3a9f1b847"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "handover_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handover_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"]),
        sa.UniqueConstraint("handover_id", "user_id", name="uq_handover_participant"),
    )
    op.create_index("ix_hp_user_role", "handover_participants", ["user_id", "role"])
    op.create_index("ix_hp_handover_role", "handover_participants", ["handover_id", "role"])

    with op.batch_alter_table("handovers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("request_state", sa.String(length=12), nullable=False,
                                      server_default="NONE"))
        batch_op.add_column(sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("requested_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("accepted_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("answered_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("request_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("answer_note", sa.Text(), nullable=True))
    op.create_index("ix_ho_request", "handovers", ["request_state", "registered_date"])

    # 지금 담당자가 있는 건은 그 사람을 '대표 담당'으로 — 보이는 것이 달라지지 않게.
    op.get_bind().execute(sa.text(
        "INSERT INTO handover_participants (handover_id, user_id, role, created_at, updated_at) "
        "SELECT id, assignee_id, 'OWNER', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM handovers WHERE assignee_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_ho_request", table_name="handovers")
    with op.batch_alter_table("handovers", schema=None) as batch_op:
        for col in ("answer_note", "request_note", "answered_by", "answered_at",
                    "accepted_by", "accepted_at", "requested_by", "requested_at",
                    "request_state"):
            batch_op.drop_column(col)
    op.drop_index("ix_hp_handover_role", table_name="handover_participants")
    op.drop_index("ix_hp_user_role", table_name="handover_participants")
    op.drop_table("handover_participants")
