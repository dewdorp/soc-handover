"""사용자별 개인 메모."""
from alembic import op
import sqlalchemy as sa

revision = "f31b8d42a670"
down_revision = "e9a4c7b2d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(title)) > 0 AND length(title) <= 200", name="ck_private_notes_title"),
        sa.CheckConstraint("length(body) <= 50000", name="ck_private_notes_body"),
        sa.CheckConstraint("version_no > 0", name="ck_private_notes_version"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_private_notes_owner_updated", "private_notes", ["owner_id", "updated_at", "id"])


def downgrade() -> None:
    op.drop_table("private_notes")
