"""백그라운드 Job 실행 — Celery 없이 DB 상태 + 프로세스 내 실행(ARCHITECTURE §3).

수십만 행 Import 는 HTTP 요청 수명 안에서 끝낼 수 없다. 요청은 Job 을 '점유(claim)'만
하고 즉시 202 를 돌려주며, 실제 작업은 응답 뒤에 돈다. 화면은 GET 으로 진행률을 폴링한다.

**점유는 조건부 UPDATE 한 문장**으로 한다. '커밋' 버튼을 두 번 눌러도, 두 탭에서 동시에
눌러도 한쪽만 성공하고 다른 쪽은 409 를 받는다. 같은 파일이 두 벌 들어가는 사고를 막는
지점이 여기다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.time import now
from app.models.importjob import JOB_CANCELED, JOB_FAILED, JOB_RUNNING, ExcelImportJob

log = logging.getLogger("app.jobs")

Progress = Callable[[int], None]
Work = Callable[[Session, ExcelImportJob, Progress], dict[str, Any] | None]


def claim(db: Session, job_id: int, allowed_from: Iterable[str], phase: str) -> bool:
    """허용된 상태에서만 RUNNING 으로 바꾼다. 성공하면 True. 호출자가 곧바로 commit 한다."""
    result = db.execute(
        update(ExcelImportJob)
        .where(ExcelImportJob.id == job_id, ExcelImportJob.status.in_(list(allowed_from)))
        .values(status=JOB_RUNNING, phase=phase, progress=0, error_message=None,
                started_at=now(), finished_at=None)
    )
    return result.rowcount == 1


def run(job_id: int, work: Work, *, success_status: str) -> None:
    """응답 뒤에 실행된다. 요청 세션과 별개인 새 세션을 쓴다."""
    with SessionLocal() as db:
        job = db.get(ExcelImportJob, job_id)
        if job is None:  # pragma: no cover - 방어적
            return

        def progress(pct: int) -> None:
            job.progress = max(0, min(100, pct))
            db.commit()

        try:
            result = work(db, job, progress)
            # 사람이 배치 경계에서 멈춘 경우 — 성공으로 적지 않는다(멈춘 자리에서 이어서 반영한다)
            if isinstance(result, dict) and result.get("canceled"):
                success_status = JOB_CANCELED
            job.status = success_status
            job.phase = None
            job.progress = 100
            job.finished_at = now()
            if result is not None:
                job.report = {**(job.report or {}), **result}
            db.commit()
        except Exception as exc:  # 실패는 삼키지 않고 Job 에 남긴다
            db.rollback()
            job = db.get(ExcelImportJob, job_id)
            job.status = JOB_FAILED
            job.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            job.finished_at = now()
            db.commit()
            log.exception("job %s 실패 (phase=%s)", job.job_code, job.phase)


def recover_stale(db: Session) -> int:
    """서버가 재기동되면 RUNNING 으로 남은 Job 은 영원히 끝나지 않는다. 실패로 정리한다.

    phase 는 남겨 두므로 어디서 멈췄는지 알 수 있고, COMMIT 은 행 단위 멱등이라 다시
    실행하면 남은 행만 들어간다.
    """
    result = db.execute(
        update(ExcelImportJob)
        .where(ExcelImportJob.status == JOB_RUNNING)
        .values(status=JOB_FAILED, finished_at=now(),
                error_message="서버가 재기동되어 작업이 중단되었습니다. 다시 실행하십시오.")
    )
    db.commit()
    if result.rowcount:
        log.warning("중단된 Import Job %d건을 실패로 정리했습니다.", result.rowcount)
    return result.rowcount
