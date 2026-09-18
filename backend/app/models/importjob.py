"""Excel Import Job / Staging Row / Error (§44~§48).

바로 DB에 넣지 않고 staging 을 거치기 위한 테이블이다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, TZDateTime

JOB_UPLOADED = "UPLOADED"
JOB_ANALYZED = "ANALYZED"
JOB_MAPPED = "MAPPED"
JOB_STAGED = "STAGED"
JOB_VALIDATED = "VALIDATED"
JOB_DEDUPED = "DEDUPED"
JOB_RUNNING = "RUNNING"
JOB_COMPLETED = "COMPLETED"
JOB_FAILED = "FAILED"
JOB_ROLLED_BACK = "ROLLED_BACK"


class ExcelImportJob(Base, TimestampMixin):
    __tablename__ = "excel_import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(400), nullable=False)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JOB_UPLOADED)
    sheet_summary: Mapped[dict | None] = mapped_column(JSONType)
    column_mapping: Mapped[dict | None] = mapped_column(JSONType)
    options: Mapped[dict | None] = mapped_column(JSONType)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: status=RUNNING 일 때 무엇을 하는 중인지(STAGE/PREPARE/COMMIT/ROLLBACK).
    #: 실패하면 그대로 남겨 어디서 멈췄는지 알 수 있게 한다.
    phase: Mapped[str | None] = mapped_column(String(20))
    #: 완료/롤백 결과 요약. 보고서 화면과 감사 증적이 같은 숫자를 보게 한다.
    report: Mapped[dict | None] = mapped_column(JSONType)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    error_message: Mapped[str | None] = mapped_column(Text)


class ExcelImportRow(Base):
    """staging. 원본을 그대로 보존한 뒤 검증/중복판정 결과를 붙인다."""
    __tablename__ = "excel_import_rows"
    __table_args__ = (
        Index("ix_imp_row_job_status", "job_id", "status"),
        Index("ix_imp_row_fingerprint", "job_id", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("excel_import_jobs.id", ondelete="CASCADE"),
                                        nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False)
    normalized: Mapped[dict | None] = mapped_column(JSONType)
    #: 막지는 않지만 사용자가 알아야 하는 것(미등록 관계사, 날짜 추정 등). 오류는 errors 테이블.
    warnings: Mapped[list | None] = mapped_column(JSONType)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    dup_type: Mapped[str] = mapped_column(String(20), nullable=False, default="NONE")
    dup_handover_id: Mapped[int | None] = mapped_column(BigInteger)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="STAGED")
    handover_id: Mapped[int | None] = mapped_column(BigInteger)


class ExcelImportError(Base):
    __tablename__ = "excel_import_errors"
    __table_args__ = (Index("ix_imp_err_job", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("excel_import_jobs.id", ondelete="CASCADE"),
                                        nullable=False)
    row_id: Mapped[int | None] = mapped_column(ForeignKey("excel_import_rows.id",
                                                          ondelete="CASCADE"))
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    column_name: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
