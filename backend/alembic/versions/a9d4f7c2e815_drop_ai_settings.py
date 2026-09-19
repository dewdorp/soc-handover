"""AI 기능 제외 — 쓰이지 않는 AI 토글 설정 4개를 지운다

AI(자연어 검색 · 임베딩 · 요약 · 태그 추천)는 범위에서 뺐다(ASSUMPTIONS E-01).
코드에서 기본값을 없애도 이미 만들어진 행은 남아 설정 화면에 뜻 없는 칸으로 보이므로 지운다.
되돌리면 모두 꺼진 상태로 다시 만든다.

Revision ID: a9d4f7c2e815
Revises: f2b8c4e6a0d7
Create Date: 2026-09-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4f7c2e815"
down_revision: Union[str, None] = "f2b8c4e6a0d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AI_KEYS = {
    "ai.search_enabled": "AI 자연어 검색 사용",
    "ai.embedding_enabled": "임베딩(Vector) 사용",
    "ai.summary_enabled": "AI 요약 사용",
    "ai.tag_suggest_enabled": "AI 태그 추천 사용",
}

settings = sa.table(
    "system_settings",
    sa.column("key", sa.String), sa.column("value", sa.JSON), sa.column("value_type", sa.String),
    sa.column("category", sa.String), sa.column("description", sa.Text), sa.column("is_secret", sa.Boolean),
)


def upgrade() -> None:
    op.execute(settings.delete().where(settings.c.key.in_(list(AI_KEYS))))


def downgrade() -> None:
    op.bulk_insert(settings, [
        {"key": k, "value": False, "value_type": "json", "category": "ai", "description": d, "is_secret": False}
        for k, d in AI_KEYS.items()
    ])
