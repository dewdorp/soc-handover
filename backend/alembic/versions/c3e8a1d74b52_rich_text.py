"""서식 있는 본문(리치 텍스트) — 본문 옆에 문서 구조 칼럼, 첨부에 '본문 그림' 구분.

기존 텍스트 칼럼은 그대로 둔다. 새 `*_doc` 칼럼이 비어 있으면 서식 없는 옛 글이고,
화면은 텍스트를 그대로 보여 준다. **기존 행은 하나도 바꾸지 않는다** — 옛 글은 누가
고칠 때만 구조로 바뀐다(일괄 변환 없음).

attachments.kind
  FILE    지금까지의 첨부(첨부 목록에 나온다)
  INLINE  본문 · 댓글에 끼운 그림(첨부 목록에 나오지 않고, 본문에서만 보인다)
  저장 전 그림은 entity_type='DRAFT' 로 올린 사람에게만 보이고, 저장할 때 그 글에 묶인다.

Revision ID: c3e8a1d74b52
Revises: b7c93e15d8a2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3e8a1d74b52"
down_revision = "b7c93e15d8a2"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

#: (표, 새 칼럼)
_DOC_COLUMNS = (
    ("handovers", "content_doc"),
    ("handover_comments", "body_doc"),
    ("knowledge_articles", "body_doc"),
    ("knowledge_revisions", "body_doc"),
    ("tasks", "description_doc"),
    ("task_comments", "body_doc"),
)


def upgrade() -> None:
    for table, column in _DOC_COLUMNS:
        op.add_column(table, sa.Column(column, _JSON, nullable=True))
    op.add_column("attachments", sa.Column("kind", sa.String(10), nullable=False,
                                           server_default="FILE"))
    op.create_index("ix_att_draft", "attachments", ["entity_type", "uploaded_by", "created_at"])


def downgrade() -> None:
    # 되돌리면 서식은 사라지고 순수 텍스트만 남는다(텍스트 칼럼은 늘 같이 저장했다).
    # 본문 그림 파일은 첨부로 남는다 — kind 칼럼이 없어지면 첨부 목록에 그림으로 보인다.
    op.drop_index("ix_att_draft", table_name="attachments")
    op.drop_column("attachments", "kind")
    for table, column in reversed(_DOC_COLUMNS):
        op.drop_column(table, column)
