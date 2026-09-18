"""Excel Import / Export 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.search.dsl import SearchRequest


class ImportJobOut(BaseModel):
    id: int
    job_code: str
    file_name: str
    status: str
    phase: str | None
    progress: int
    total_rows: int
    success_rows: int
    duplicate_rows: int
    error_rows: int
    skipped_rows: int
    sheet_summary: dict[str, Any] | None
    column_mapping: dict[str, Any] | None
    options: dict[str, Any] | None
    report: dict[str, Any] | None
    error_message: str | None
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class MappingRequest(BaseModel):
    """③ 컬럼 매핑 확정. 매핑하지 않은 컬럼도 원본에 그대로 보존된다."""
    sheets: list[str] = Field(min_length=1, max_length=100)
    column_mapping: dict[str, str | None]
    #: 진행상황이 비어 있거나 알 수 없을 때 쓸 상태. 과거 기록은 대부분 끝난 일이라 기본 DONE.
    default_status: str = Field(default="DONE", max_length=20)
    #: 날짜에 연도가 없고 시트 이름에서도 못 찾을 때 쓸 연도
    default_year: int | None = Field(default=None, ge=1990, le=2100)


class ValueMapRequest(BaseModel):
    """값 매핑. company 는 원문 → 관계사 id 또는 '__CREATE__', status 는 원문 → 상태 코드."""
    field: Literal["company", "status"]
    mapping: dict[str, int | str | None]


class DecisionRequest(BaseModel):
    row_ids: list[int] = Field(min_length=1, max_length=5000)
    decision: Literal["IMPORT", "SKIP", "PENDING"]


class RowOut(BaseModel):
    id: int
    sheet_name: str
    source_row: int
    raw: dict[str, Any]
    normalized: dict[str, Any] | None
    warnings: list[dict[str, Any]] | None
    fingerprint: str | None
    dup_type: str
    dup_handover_id: int | None
    decision: str
    status: str
    handover_id: int | None
    will_import: bool = False

    model_config = {"from_attributes": True}


class ErrorOut(BaseModel):
    id: int
    row_id: int | None
    sheet_name: str | None
    source_row: int | None
    column_name: str | None
    error_code: str
    message: str
    raw_value: str | None

    model_config = {"from_attributes": True}


class ValueStat(BaseModel):
    """값 매핑 화면의 한 줄: 엑셀 원문, 건수, 지금 무엇으로 연결되는지."""
    value: str
    #: 표기만 다른 원문들(대표 표기 포함). 하나로 묶어 한 번에 매핑한다.
    variants: list[str] = []
    count: int
    target: Any = None
    target_label: str | None = None
    matched: bool


class ExportRequest(SearchRequest):
    """목록과 **같은 DSL** 을 받는다. 화면에 보이는 결과 = 내려받는 결과(FR-F-07)."""
    columns: list[str] | None = Field(default=None, max_length=40)
    format: Literal["xlsx", "csv"] = "xlsx"


class ExportOut(BaseModel):
    download_token: str
    file_name: str
    rows: int
    expires_at: datetime
