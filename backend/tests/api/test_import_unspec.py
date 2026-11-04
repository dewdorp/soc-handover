"""예약 코드(UNSPEC) 재사용 — 이름이 바뀐 현장 DB 에서도 깨지지 않아야 한다(재현 ⑤).

현장에서 '미지정' 을 '공통' 으로 고쳐 쓰는 일이 있다. 그때 이름으로만 찾고 code='UNSPEC' 로
새로 만들면 고유키(code) 에서 터진다 — 가져오기 전체가 멈춘다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.reference import Company
from app.services import bootstrap_service

from tests.excel_factory import XLSX, build_workbook

JOBS = "/api/v1/import/jobs"


@pytest.fixture
def renamed_default(db):
    """예약 코드는 그대로 두고 표시명만 '공통' 으로 바꾼 현장 상태."""
    company = bootstrap_service.ensure_default_company(db)
    company.name = "공통"
    db.commit()
    return company


class TestReservedCodeIsReused:
    def test_bootstrap_does_not_insert_a_second_unspec(self, db, renamed_default):
        again = bootstrap_service.ensure_default_company(db)
        db.commit()
        assert again.id == renamed_default.id, "이름이 아니라 예약 코드로 찾는다"
        assert again.name == "공통", "현장에서 고친 이름을 되돌리지 않는다"
        rows = db.scalars(select(Company).where(Company.code == "UNSPEC")).all()
        assert len(rows) == 1

    def test_import_commits_with_renamed_default(self, admin_client, db, renamed_default):
        """매칭 실패 행이 있어도 '미지정'을 또 만들지 않고 기존 예약 코드로 보낸다."""
        job = admin_client.post(JOBS, files={"file": ("인수인계_2025.xlsx", build_workbook(), XLSX)}).json()
        mapped = admin_client.post(f"{JOBS}/{job['id']}/mapping", json={
            "sheets": job["options"]["sheets"], "column_mapping": job["column_mapping"],
            "default_status": "DONE"})
        assert mapped.status_code == 200, mapped.text
        assert admin_client.post(f"{JOBS}/{job['id']}/stage").status_code == 202
        committed = admin_client.post(f"{JOBS}/{job['id']}/commit")
        assert committed.status_code == 202, committed.text
        done = admin_client.get(f"{JOBS}/{job['id']}").json()
        assert done["status"] == "COMPLETED", done

        rows = db.scalars(select(Company).where(Company.code == "UNSPEC")).all()
        assert len(rows) == 1, "예약 코드가 둘이 되면 안 된다"
