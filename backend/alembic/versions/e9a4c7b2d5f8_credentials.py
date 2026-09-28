"""장비 비밀번호 보관 — credentials · credential_versions

현장 요청: 관계사 장비의 접속 계정 · 비밀번호를 한 곳에 두고 교대하며 같이 쓴다.
비밀번호는 평문으로 두지 않는다 — AES-256-GCM 암호문(app/core/crypto.py)만 저장한다.

Revision ID: e9a4c7b2d5f8
Revises: d5c8b2a6f931
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9a4c7b2d5f8"
down_revision: Union[str, None] = "d5c8b2a6f931"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STR_LIST = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("device_name", sa.String(length=200), nullable=False),
        sa.Column("access_method", sa.Text(), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("secret_cipher", sa.LargeBinary(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_by", sa.Integer(), nullable=True),
        sa.Column("current_version_no", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["rotated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("credentials", schema=None) as batch_op:
        batch_op.create_index("ix_cred_scope_owner", ["scope", "owner_id", "is_deleted"], unique=False)
        batch_op.create_index("ix_cred_device", ["device_name"], unique=False)
        batch_op.create_index("ix_cred_company", ["company_id"], unique=False)

    op.create_table(
        "credential_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("secret_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("changed_fields", STR_LIST, nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("device_name", sa.String(length=200), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("key_version", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("credential_versions", schema=None) as batch_op:
        batch_op.create_index("ix_credver_cred", ["credential_id", "version_no"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("credential_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_credver_cred")
    op.drop_table("credential_versions")
    with op.batch_alter_table("credentials", schema=None) as batch_op:
        batch_op.drop_index("ix_cred_company")
        batch_op.drop_index("ix_cred_device")
        batch_op.drop_index("ix_cred_scope_owner")
    op.drop_table("credentials")
