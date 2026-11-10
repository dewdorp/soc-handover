"""그룹 미지정 과거 자료의 '전체 공개 전환' 이력 표를 만든다.

**이 마이그레이션은 어떤 자료의 공개 범위도 바꾸지 않는다.**
올리는 즉시 과거 자료가 전체 공개로 바뀌면, 관리자가 내용을 확인하기도 전에
외주 계정까지 내부 인계가 보인다. 그래서 전환은 관리자가 화면에서
건수·목록을 확인하고, 경고를 읽고, 백업을 확인한 뒤 직접 승인할 때만 수행한다
(/api/v1/groups/public-migration — group_service.public_migration_* 참고).

여기서는 전환 이력 표만 만든다. 이 표가 있어야 전환을 되돌릴 수 있다.

Revision ID: c60e8b91f4a2
Revises: f6d2b8a4c137
"""
import sqlalchemy as sa
from alembic import op

revision = "c60e8b91f4a2"
down_revision = "f6d2b8a4c137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind()
    names = set(sa.inspect(db).get_table_names())
    if "scope_public_migration" in names:      # 앞선 시도에서 이미 만들었다
        return
    op.create_table(
        "scope_public_migration",
        # 전환한 업무 한 건 = 한 줄. 되돌리면 reverted_at 이 찍히고 줄은 남는다.
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(32), nullable=False),
        sa.Column("handover_id", sa.Integer(), nullable=False),
        #: 전환 전에 '미분류' 그룹에 걸려 있었는가 — 되돌릴 때 이 링크를 되살린다
        sa.Column("had_unclassified", sa.Boolean(), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_by", sa.Integer(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("batch_id", "handover_id", name="uq_scope_public_batch_row"),
    )
    op.create_index("ix_scope_public_handover", "scope_public_migration", ["handover_id"])


def downgrade() -> None:
    # 아직 되돌리지 않은 전환을 먼저 원래대로 돌려놓는다. 표를 지우면 복구할 길이 없다.
    db = op.get_bind()
    names = set(sa.inspect(db).get_table_names())
    if "scope_public_migration" not in names:
        return
    db.execute(sa.text("""
        UPDATE handovers SET visibility = 'GROUPS'
        WHERE id IN (SELECT handover_id FROM scope_public_migration WHERE reverted_at IS NULL)
    """))
    db.execute(sa.text("""
        INSERT INTO handover_groups (handover_id, group_id)
        SELECT m.handover_id, g.id
        FROM scope_public_migration m
        CROSS JOIN groups g
        WHERE m.reverted_at IS NULL AND m.had_unclassified = :yes AND g.code = 'UNCLASSIFIED'
          AND NOT EXISTS (SELECT 1 FROM handover_groups hg
                          WHERE hg.handover_id = m.handover_id AND hg.group_id = g.id)
    """), {"yes": True})
    op.drop_index("ix_scope_public_handover", table_name="scope_public_migration")
    op.drop_table("scope_public_migration")
