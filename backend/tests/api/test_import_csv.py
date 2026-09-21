"""CSV · TSV Import — Excel 과 같은 마법사로 끝까지 간다(현장 요청).

현장 CSV 는 인코딩(한국어 Windows Excel = cp949)과 구분자가 제각각이라 그 부분을 집중해서 본다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.handover import Handover
from app.models.reference import Company
from tests.excel_factory import CSV_MIME, XLSX, build_csv, build_workbook

JOBS = "/api/v1/import/jobs"


@pytest.fixture
def companies(db):
    for name in ("A보안", "B금융"):
        db.add(Company(name=name))
    db.commit()


def _upload(client, content: bytes, name: str):
    return client.post(JOBS, files={"file": (name, content, CSV_MIME)})


def _run(client, content: bytes, name: str = "인수인계.csv") -> dict:
    """업로드 → 매핑 → 적재 → 반영. 마법사 전체를 CSV 로 한 바퀴."""
    job = _upload(client, content, name).json()
    mapped = client.post(f"{JOBS}/{job['id']}/mapping", json={
        "sheets": job["options"]["sheets"],
        "column_mapping": job["column_mapping"],
        "default_status": "DONE",
    })
    assert mapped.status_code == 200, mapped.text
    assert client.post(f"{JOBS}/{job['id']}/stage").status_code == 202
    assert client.get(f"{JOBS}/{job['id']}").json()["status"] == "DEDUPED"
    committed = client.post(f"{JOBS}/{job['id']}/commit")
    assert committed.status_code == 202, committed.text
    done = client.get(f"{JOBS}/{job['id']}").json()
    assert done["status"] == "COMPLETED", done
    return done


class TestCsvUpload:
    def test_utf8_csv_is_analyzed_like_a_sheet(self, admin_client, companies):
        resp = _upload(admin_client, build_csv("utf-8-sig"), "인수인계_2025.csv")
        assert resp.status_code == 201, resp.text
        job = resp.json()
        sheets = job["sheet_summary"]["sheets"]
        assert len(sheets) == 1, "CSV 는 Sheet 하나로 본다"
        sheet = sheets[0]
        assert sheet["name"] == "인수인계_2025", "파일 이름이 Sheet 이름이 된다"
        assert sheet["header_row"] == 3, "제목 줄 · 빈 줄을 건너뛰고 헤더를 찾는다"
        assert "관계사" in sheet["headers"] and "진행상황" in sheet["headers"]
        assert sheet["estimated_rows"] >= 4
        assert job["column_mapping"]["관계사"] == "company"

    def test_cp949_csv_keeps_korean(self, admin_client, companies):
        """한국어 Windows 의 Excel 이 저장한 CSV(cp949)."""
        job = _upload(admin_client, build_csv("cp949"), "인수인계.csv").json()
        sheet = job["sheet_summary"]["sheets"][0]
        assert "관계사" in sheet["headers"], f"헤더가 깨졌다: {sheet['headers']}"
        assert any("방화벽" in str(v) for row in sheet["samples"] for v in row.values())

    def test_tab_separated_file(self, admin_client, companies):
        job = _upload(admin_client, build_csv("utf-8", "\t"), "인수인계.tsv").json()
        assert "관계사" in job["sheet_summary"]["sheets"][0]["headers"]

    def test_semicolon_csv(self, admin_client, companies):
        job = _upload(admin_client, build_csv("utf-8-sig", ";"), "인수인계.csv").json()
        assert "관계사" in job["sheet_summary"]["sheets"][0]["headers"]

    def test_excel_file_renamed_to_csv_is_refused(self, admin_client):
        resp = _upload(admin_client, build_workbook(), "사실은엑셀.csv")
        assert resp.status_code == 422
        assert "Excel" in resp.json()["message"]

    def test_csv_without_headers_is_refused(self, admin_client):
        resp = _upload(admin_client, "".encode(), "빈파일.csv")
        assert resp.status_code == 422

    def test_xlsx_still_works(self, admin_client, companies):
        resp = admin_client.post(JOBS, files={"file": ("인수인계.xlsx", build_workbook(), XLSX)})
        assert resp.status_code == 201
        assert len(resp.json()["sheet_summary"]["sheets"]) == 3, "Excel 은 그대로 Sheet 여러 개"


class TestCsvCommit:
    def test_rows_land_with_source_tracking(self, admin_client, companies, db):
        job = _run(admin_client, build_csv("cp949"), "인수인계_2025.csv")
        assert job["success_rows"] == 3, "빈 줄은 빼고 3건"

        rows = db.scalars(select(Handover).order_by(Handover.id)).all()
        assert [r.company.name for r in rows] == ["A보안", "B금융", "A보안"]
        assert rows[0].content.startswith("방화벽 정책 변경")
        assert rows[1].content == 'EDR 경고 조사, "우선순위 높음"', "따옴표 · 쉼표가 든 값도 그대로"
        assert rows[0].source_file.endswith(".csv") and rows[0].source_sheet == "인수인계_2025"
        assert [r.source_row for r in rows] == [4, 5, 7], "원본 줄 번호를 그대로 남긴다(빈 줄 6 건너뜀)"
        assert rows[0].sender_name_raw == "홍길동" and rows[0].checker_name_raw == "김철수"

    def test_same_csv_twice_is_detected_as_duplicate(self, admin_client, companies):
        _run(admin_client, build_csv("utf-8-sig"), "인수인계_2025.csv")
        again = _run(admin_client, build_csv("utf-8-sig"), "인수인계_2025.csv")
        assert again["success_rows"] == 0
        assert again["duplicate_rows"] == 3, "같은 파일을 또 올리면 중복으로 잡는다"
