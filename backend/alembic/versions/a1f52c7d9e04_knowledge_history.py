"""운영 지식: 태그 · 개정 이력 · 인수인계 연결.

개정 이력이 없으면 '그때 절차에 무엇이라고 적혀 있었는지'를 댈 수 없고,
버전 비교와 복원도 못 한다(§4). 연결표는 인수인계 화면에서 관련 절차를 바로
여는 데 쓰며, 연결 자체가 열람 권한을 넓히지는 않는다.

Revision ID: a1f52c7d9e04
Revises: d7e3a4c8061f
"""
import sqlalchemy as sa
from alembic import op

revision = "a1f52c7d9e04"
down_revision = "d7e3a4c8061f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(),
                  sa.ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag", sa.String(40), nullable=False),
        sa.UniqueConstraint("article_id", "tag", name="uq_knowledge_tag"),
    )
    op.create_index("ix_knowledge_tag", "knowledge_tags", ["tag"])

    op.create_table(
        "knowledge_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(),
                  sa.ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="ALL"),
        sa.Column("tags", sa.String(500), nullable=False, server_default=""),
        sa.Column("change_note", sa.String(300), nullable=True),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("article_id", "version_no", name="uq_knowledge_revision"),
    )
    op.create_index("ix_knowledge_revision_article", "knowledge_revisions",
                    ["article_id", "version_no"])

    op.create_table(
        "knowledge_handover_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(),
                  sa.ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("handover_id", sa.Integer(),
                  sa.ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("article_id", "handover_id", name="uq_knowledge_handover"),
    )
    op.create_index("ix_knowledge_link_handover", "knowledge_handover_links", ["handover_id"])

    # 이미 등록된 문서에도 '1판' 이력을 만들어 둔다 — 이력이 없는 문서가 섞이면
    # 화면이 '이력 없음'과 '아직 안 바뀜'을 구분하지 못한다.
    db = op.get_bind()
    db.execute(sa.text("""
        INSERT INTO knowledge_revisions
            (article_id, version_no, category, title, body, visibility, tags,
             change_note, changed_by, changed_at)
        SELECT a.id, a.version_no, a.category, a.title, a.body, a.visibility, '',
               '패치 전 상태', a.created_by, a.updated_at
        FROM knowledge_articles a
    """))


def downgrade() -> None:
    op.drop_index("ix_knowledge_link_handover", table_name="knowledge_handover_links")
    op.drop_table("knowledge_handover_links")
    op.drop_index("ix_knowledge_revision_article", table_name="knowledge_revisions")
    op.drop_table("knowledge_revisions")
    op.drop_index("ix_knowledge_tag", table_name="knowledge_tags")
    op.drop_table("knowledge_tags")
