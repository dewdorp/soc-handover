"""Phase 10 — 감사로그 보관 정리: 보존기간 지난 것만, 내보낸 뒤 확인하고 지우며, 그 행위도 감사에 남긴다."""
from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.time import KST
from app.models.common import AuditLog
from app.services import audit_archive_service


def _log(db, days_ago: int, action: str = "LOGIN_SUCCESS", **extra):
    db.add(AuditLog(event_uuid=uuid.uuid4().hex, occurred_at=datetime.now(KST) - timedelta(days=days_ago),
                    action=action, result="SUCCESS", username="hong", **extra))


@pytest.fixture
def seeded(db):
    for d in (800, 500, 400):
        _log(db, d, detail={"note": f"{d}일 전", "한글": True}, client_ip="10.0.0.5")
    for d in (100, 1):
        _log(db, d)
    db.commit()


def test_archives_only_expired_then_deletes(db, seeded, tmp_path):
    r = audit_archive_service.archive_expired(db, days=365, out_dir=tmp_path)
    assert r["count"] == 3

    path = Path(r["file"])
    assert path.parent == tmp_path
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert len(rows) == 3
    assert {row["detail"]["note"] for row in rows} == {"800일 전", "500일 전", "400일 전"}
    assert rows[0]["client_ip"] == "10.0.0.5" and rows[0]["username"] == "hong"

    sha_line = (tmp_path / (path.name + ".sha256")).read_text(encoding="ascii")
    assert sha_line.split()[0] == hashlib.sha256(path.read_bytes()).hexdigest() == r["sha256"]

    left = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at)).all()
    kept = [a for a in left if a.action == "LOGIN_SUCCESS"]
    assert len(kept) == 2, "보존기간 안의 것은 남는다"
    archive = [a for a in left if a.action == "AUDIT_ARCHIVE"]
    assert len(archive) == 1 and archive[0].detail["count"] == 3 and archive[0].username == "system"


def test_dry_run_and_nothing_to_do(db, seeded, tmp_path):
    r = audit_archive_service.archive_expired(db, days=365, out_dir=tmp_path, dry_run=True)
    assert r["count"] == 3 and r["file"] is None
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 5, "확인만 하면 지우지 않는다"
    assert not list(tmp_path.iterdir())

    r = audit_archive_service.archive_expired(db, days=1000, out_dir=tmp_path)
    assert r["count"] == 0 and r["file"] is None


def test_minimum_retention_is_enforced(db, seeded, tmp_path):
    with pytest.raises(ValueError):
        audit_archive_service.archive_expired(db, days=30, out_dir=tmp_path)
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 5


def test_uses_retention_setting(db, seeded, tmp_path, admin_client):
    assert admin_client.patch("/api/v1/settings/retention.audit_days", json={"value": 600}).status_code == 200
    r = audit_archive_service.archive_expired(db, out_dir=tmp_path)
    assert r["days"] == 600 and r["count"] == 1, "설정한 보존일수(600일)보다 오래된 800일 전 한 건만"
