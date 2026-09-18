"""Import 처리량 — NFR-04 '분당 10,000행 이상'.

기본 실행에 포함된다. 빼려면 -m "not perf".
SQLite 기준 측정이다. 운영(PostgreSQL)은 쓰기 동시성이 더 좋다.
"""
from __future__ import annotations

import time

import pytest

from app.models.reference import Company
from tests.excel_factory import XLSX, build_large

JOBS = "/api/v1/import/jobs"
ROWS_PER_SHEET = 5_000
SHEETS = 2


@pytest.mark.perf
def test_ten_thousand_rows_within_a_minute(admin_client, db, users):
    for name in ("A보안", "B금융"):
        db.add(Company(name=name))
    db.commit()

    content = build_large(ROWS_PER_SHEET, SHEETS)
    total = ROWS_PER_SHEET * SHEETS

    t0 = time.perf_counter()
    job = admin_client.post(JOBS, files={"file": ("big.xlsx", content, XLSX)}).json()
    admin_client.post(f"{JOBS}/{job['id']}/mapping", json={
        "sheets": job["options"]["sheets"], "column_mapping": job["column_mapping"]})
    t1 = time.perf_counter()
    assert admin_client.post(f"{JOBS}/{job['id']}/stage").status_code == 202
    t2 = time.perf_counter()
    assert admin_client.post(f"{JOBS}/{job['id']}/commit").status_code == 202
    t3 = time.perf_counter()

    done = admin_client.get(f"{JOBS}/{job['id']}").json()
    assert done["status"] == "COMPLETED", done
    assert done["success_rows"] == total

    elapsed = t3 - t0
    rate = total / elapsed * 60
    print(f"\n[perf] {total:,}행 · 업로드+분석 {t1 - t0:.1f}s · 적재+검증+중복 {t2 - t1:.1f}s "
          f"· 반영 {t3 - t2:.1f}s · 합계 {elapsed:.1f}s · {rate:,.0f}행/분")
    assert rate >= 10_000, f"NFR-04 미달: {rate:,.0f}행/분"
