"""PostgreSQL 전용 검색 객체(trigram · tsvector · 부분 인덱스)

PostgreSQL 에서만 생성되며, SQLite 에서는 아무 것도 하지 않는다.
한글 형태소 사전 없이도 검색 품질을 확보하기 위해 trigram 과 simple tsvector 를 함께 쓴다
(ARCHITECTURE.md §5.3).

Revision ID: a1b2c3d4e5f6
Revises: d28665e5d3a6
Create Date: 2026-09-16
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d28665e5d3a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("alembic.postgres_search")

TSV_TRIGGER = """
CREATE OR REPLACE FUNCTION handovers_search_tsv_update() RETURNS trigger AS $$
BEGIN
    NEW.search_tsv := to_tsvector('simple', coalesce(NEW.search_text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # pg_trgm 은 contrib 기본 포함. 권한이 없으면 경고만 남기고 LIKE 로 degrade 한다.
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        has_trgm = True
    except Exception:  # pragma: no cover - 권한 없는 환경
        log.warning("pg_trgm 확장을 만들지 못했습니다. 부분일치 검색이 느려질 수 있습니다.")
        has_trgm = False

    op.execute("ALTER TABLE handovers ADD COLUMN IF NOT EXISTS search_tsv tsvector")
    op.execute(TSV_TRIGGER)
    op.execute("DROP TRIGGER IF EXISTS trg_handovers_search_tsv ON handovers")
    op.execute(
        "CREATE TRIGGER trg_handovers_search_tsv BEFORE INSERT OR UPDATE OF search_text "
        "ON handovers FOR EACH ROW EXECUTE FUNCTION handovers_search_tsv_update()"
    )
    op.execute(
        "UPDATE handovers SET search_tsv = to_tsvector('simple', coalesce(search_text, ''))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ho_tsv ON handovers USING gin (search_tsv)")
    if has_trgm:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ho_trgm ON handovers "
            "USING gin (search_text gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_tag_trgm ON tags USING gin (name gin_trgm_ops)"
        )

    # 부분 인덱스: 삭제되지 않은 행만 대상으로 해 인덱스 크기를 줄인다(ERD §4)
    op.execute("DROP INDEX IF EXISTS ix_ho_company_date")
    op.execute("CREATE INDEX ix_ho_company_date ON handovers (company_id, registered_date DESC) "
               "WHERE is_deleted = false")
    op.execute("DROP INDEX IF EXISTS ix_ho_open")
    op.execute("CREATE INDEX ix_ho_open ON handovers (status_code, work_date) "
               "WHERE is_deleted = false")
    op.execute("DROP INDEX IF EXISTS ix_ho_assignee")
    op.execute("CREATE INDEX ix_ho_assignee ON handovers (assignee_id, status_code, work_date) "
               "WHERE is_deleted = false")
    op.execute("DROP INDEX IF EXISTS ix_ho_ack")
    op.execute("CREATE INDEX ix_ho_ack ON handovers (ack_state_cache) "
               "WHERE is_deleted = false AND ack_state_cache <> 'ACKED'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ho_important ON handovers "
               "(is_pinned DESC, is_important DESC, registered_date DESC) "
               "WHERE is_deleted = false AND (is_pinned OR is_important)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_open_due ON tasks (due_date) "
               "WHERE status NOT IN ('DONE', 'CANCELED') AND is_deleted = false")

    # 사용자당 Basket(DRAFT 세션)은 하나만 존재할 수 있다
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_basket_per_user "
               "ON shift_handovers (from_user_id) WHERE status = 'DRAFT'")
    # 읽지 않은 알림의 중복 생성 방지(알림 폭주 방지)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_noti_dedup "
               "ON notifications (user_id, dedup_key) WHERE is_read = false "
               "AND dedup_key IS NOT NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for stmt in (
        "DROP INDEX IF EXISTS uq_noti_dedup",
        "DROP INDEX IF EXISTS uq_basket_per_user",
        "DROP INDEX IF EXISTS ix_task_open_due",
        "DROP INDEX IF EXISTS ix_ho_important",
        "DROP INDEX IF EXISTS ix_tag_trgm",
        "DROP INDEX IF EXISTS ix_ho_trgm",
        "DROP INDEX IF EXISTS ix_ho_tsv",
        "DROP TRIGGER IF EXISTS trg_handovers_search_tsv ON handovers",
        "DROP FUNCTION IF EXISTS handovers_search_tsv_update()",
        "ALTER TABLE handovers DROP COLUMN IF EXISTS search_tsv",
    ):
        op.execute(stmt)
