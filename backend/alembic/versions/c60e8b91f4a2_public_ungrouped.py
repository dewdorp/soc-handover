"""미분류(그룹 미지정) 기존 인수인계를 전체 공개로 전환.

관리자가 특정 그룹을 지정한 자료는 건드리지 않는다.
과거 그룹 링크는 복구 가능한 보조 테이블에 남겨 downgrade 시 복원한다.

Revision ID: c60e8b91f4a2
Revises: f6d2b8a4c137
"""
from alembic import op
import sqlalchemy as sa

revision = "c60e8b91f4a2"
down_revision = "f6d2b8a4c137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scope_public_migration",
        sa.Column("handover_id", sa.Integer(), primary_key=True),
        sa.Column("had_unclassified", sa.Boolean(), nullable=False),
    )
    db = op.get_bind()
    # 다른 실제 그룹을 한 곳이라도 지정한 인수인계는 절대 공개하지 않는다.
    eligible = """
        SELECT h.id
        FROM handovers h
        WHERE h.visibility = 'GROUPS'
          AND NOT EXISTS (
            SELECT 1 FROM handover_groups hg
            JOIN groups g ON g.id = hg.group_id
            WHERE hg.handover_id = h.id AND COALESCE(g.code, '') != 'UNCLASSIFIED'
          )
    """
    db.execute(sa.text("""
        INSERT INTO scope_public_migration (handover_id, had_unclassified)
        SELECT h.id,
          CASE WHEN EXISTS (
            SELECT 1 FROM handover_groups hg JOIN groups g ON g.id = hg.group_id
            WHERE hg.handover_id = h.id AND g.code = 'UNCLASSIFIED'
          ) THEN :yes ELSE :no END
        FROM handovers h
        WHERE h.id IN (""" + eligible + ")"), {"yes": True, "no": False})
    db.execute(sa.text("""
        UPDATE handovers SET visibility = 'ALL'
        WHERE id IN (SELECT handover_id FROM scope_public_migration)
    """))
    db.execute(sa.text("""
        DELETE FROM handover_groups
        WHERE handover_id IN (SELECT handover_id FROM scope_public_migration)
          AND group_id IN (SELECT id FROM groups WHERE code = 'UNCLASSIFIED')
    """))


def downgrade() -> None:
    db = op.get_bind()
    db.execute(sa.text("""
        UPDATE handovers SET visibility = 'GROUPS'
        WHERE id IN (SELECT handover_id FROM scope_public_migration)
    """))
    db.execute(sa.text("""
        INSERT INTO handover_groups (handover_id, group_id)
        SELECT m.handover_id, g.id FROM scope_public_migration m
        CROSS JOIN groups g
        WHERE m.had_unclassified = :yes AND g.code = 'UNCLASSIFIED'
          AND NOT EXISTS (
            SELECT 1 FROM handover_groups hg
            WHERE hg.handover_id = m.handover_id AND hg.group_id = g.id
          )
    """), {"yes": True})
    op.drop_table("scope_public_migration")
