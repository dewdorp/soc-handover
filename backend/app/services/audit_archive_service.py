"""감사로그 보관 정리 (SECURITY §감사 · ASSUMPTIONS B-14).

보존기간(`retention.audit_days`, 최소 365일)이 지난 감사로그를
1) `backup/audit-archive/*.jsonl.gz` 로 **먼저 내보내고**(한 줄에 한 건, 원래 값 그대로)
2) 내보낸 건수를 다시 세어 맞는지 확인한 뒤
3) DB 에서 지운다. 이 정리 자체도 `AUDIT_ARCHIVE` 로 감사에 남는다.

앱은 감사로그를 고치거나 지우지 않는다 — 이 배치가 유일한 예외다(backup.ps1 이 매일 백업 직후 실행하므로
지워진 행은 그날 DB 백업에도 들어 있다). 보관 파일은 지우지 않는다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.config import settings
from app.models.common import AuditLog
from app.services import settings_service

MIN_DAYS = 365
BATCH = 2000

_COLUMNS = [c.name for c in AuditLog.__table__.columns]


def _row(log: AuditLog) -> dict[str, Any]:
    out = {}
    for name in _COLUMNS:
        v = getattr(log, name)
        out[name] = v.isoformat() if isinstance(v, datetime) else (str(v) if name == "client_ip" and v else v)
    return out


def archive_expired(db: Session, *, days: int | None = None, out_dir: Path | None = None,
                    now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    days = int(days or settings_service.get_value(db, "retention.audit_days") or MIN_DAYS)
    if days < MIN_DAYS:
        raise ValueError(f"감사로그는 최소 {MIN_DAYS}일 보존합니다.")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    expired = (AuditLog.occurred_at < cutoff,)
    count, max_id = db.execute(select(func.count(), func.max(AuditLog.id)).where(*expired)).one()
    result: dict[str, Any] = {"days": days, "cutoff": cutoff.isoformat(), "count": count or 0, "file": None}
    if dry_run or not count:
        return result

    out_dir = out_dir or (settings.BACKUP_DIR / "audit-archive")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"audit_before_{cutoff:%Y%m%d}_{now:%Y%m%d_%H%M%S}.jsonl.gz"

    written = 0
    last_id = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        while True:
            rows = db.scalars(select(AuditLog).where(*expired, AuditLog.id > last_id, AuditLog.id <= max_id)
                              .order_by(AuditLog.id).limit(BATCH)).all()
            if not rows:
                break
            for log in rows:
                f.write(json.dumps(_row(log), ensure_ascii=False, default=str) + "\n")
            written += len(rows)
            last_id = rows[-1].id
            db.expunge_all()

    # 파일을 다시 읽어 건수를 확인한 뒤에만 지운다(쓰다 끊긴 파일로 원본을 잃지 않게)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        reread = sum(1 for _ in f)
    if reread != written or written != count:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"보관 파일 검증 실패(대상 {count}, 기록 {written}, 다시 읽음 {reread}) — 지우지 않았습니다.")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path) + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")

    db.execute(delete(AuditLog).where(*expired, AuditLog.id <= max_id))
    record(db, action=actions.AUDIT_ARCHIVE, username="system", role_code="SYSTEM",
           resource_type="AUDIT", resource_id=path.name,
           detail={"count": written, "days": days, "before": cutoff.isoformat(), "file": path.name,
                   "sha256": digest})
    db.commit()
    result.update(file=str(path), sha256=digest)
    return result
