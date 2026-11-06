"""SOC 운영 지식 페이지와 그룹 공개 (문서 파일은 기존 attachments 저장소 사용).

Revision ID: d7e3a4c8061f
Revises: c60e8b91f4a2
"""
from alembic import op
import sqlalchemy as sa

revision = "d7e3a4c8061f"
down_revision = "c60e8b91f4a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="운영 절차"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="ALL"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_due", sa.Date(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_recent", "knowledge_articles", ["is_deleted", "updated_at"])
    op.create_index("ix_knowledge_category", "knowledge_articles", ["category", "is_deleted"])
    op.create_table(
        "knowledge_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(),
                  sa.ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("article_id", "group_id", name="uq_knowledge_group"),
    )
    op.create_index("ix_knowledge_group_gid", "knowledge_groups", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_group_gid", table_name="knowledge_groups")
    op.drop_table("knowledge_groups")
    op.drop_index("ix_knowledge_category", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_recent", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")
