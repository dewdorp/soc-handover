"""정기 점검의 회차별 완료 표시.

'점검' 종류의 반복 일정 하나가 매일·매주 회차를 만든다. 완료를 일정 자체에 적으면
한 번 끝낸 뒤 다음 회차도 끝난 것으로 보인다. 그래서 회차(그 날)마다 한 줄 남긴다.

Revision ID: b7c93e15d8a2
Revises: a1f52c7d9e04
"""
import sqlalchemy as sa
from alembic import op

revision = "b7c93e15d8a2"
down_revision = "a1f52c7d9e04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.Integer(),
                  sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("done_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("schedule_id", "occurrence_date", name="uq_sched_completion"),
    )
    op.create_index("ix_sched_completion_date", "schedule_completions", ["occurrence_date"])


def downgrade() -> None:
    op.drop_index("ix_sched_completion_date", table_name="schedule_completions")
    op.drop_table("schedule_completions")
