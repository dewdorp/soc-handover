"""Export 통합 테스트 — 화면 결과 = 내려받은 결과, 수식 주입 차단, 내려받기 권한."""
from __future__ import annotations

import csv
import io

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.main import app
from app.models.common import AuditLog
from app.models.reference import Company
from app.services import settings_service
from tests.conftest import ANALYST_PW, ApiClient

EXPORT = "/api/v1/export/handovers"


@pytest.fixture
def data(admin_client, db):
    cid = db.scalar(select(Company.id).order_by(Company.id))
    rows = [
        {"title": "DDoS 공격 탐지", "status_code": "IN_PROGRESS", "priority_code": "URGENT"},
        {"title": "방화벽 정책 변경", "status_code": "DONE"},
        {"title": "EDR 경고 조사", "status_code": "IN_PROGRESS"},
        {"title": "=HYPERLINK(\"http://evil\",\"클릭\")", "status_code": "NEW",
         "remark": "@SUM(1+1)"},
    ]
    for r in rows:
        resp = admin_client.post("/api/v1/handovers", json={"company_id": cid, "content": "c", **r})
        assert resp.status_code == 201, resp.text
    return cid


def _download(client, body) -> tuple[bytes, dict]:
    resp = client.post(EXPORT, json=body)
    assert resp.status_code == 200, resp.text
    meta = resp.json()
    file = client.get(f"/api/v1/export/download/{meta['download_token']}")
    assert file.status_code == 200
    return file.content, meta


def _xlsx_rows(content: bytes) -> list[tuple]:
    ws = load_workbook(io.BytesIO(content))["인수인계"]
    return list(ws.iter_rows(values_only=True))


class TestSameResultAsScreen:
    def test_filtered_export_matches_search(self, admin_client, data):
        dsl = {"filters": [{"field": "status_code", "op": "in", "value": ["IN_PROGRESS"]}],
               "sort": [{"field": "id", "dir": "asc"}]}
        screen = admin_client.post("/api/v1/handovers/search", json=dsl).json()
        content, meta = _download(admin_client, dsl)
        rows = _xlsx_rows(content)
        assert meta["rows"] == screen["total"] == 2
        titles = [r[rows[0].index("제목")] for r in rows[1:]]
        assert titles == [i["title"] for i in screen["items"]], "순서까지 화면과 같아야 한다"

    def test_quick_filters_apply_too(self, admin_client, data):
        _, meta = _download(admin_client, {"quick": ["OPEN"]})
        screen = admin_client.post("/api/v1/handovers/search", json={"quick": ["OPEN"]}).json()
        assert meta["rows"] == screen["total"] == 3

    def test_export_is_not_limited_to_one_page(self, admin_client, data):
        """화면은 50행씩 보여도 Export 는 조건에 맞는 전부를 준다."""
        _, meta = _download(admin_client, {"size": 1})
        assert meta["rows"] == 4

    def test_columns_can_be_chosen(self, admin_client, data):
        content, _ = _download(admin_client, {"columns": ["id", "title"]})
        assert _xlsx_rows(content)[0] == ("번호", "제목")

    def test_conditions_are_recorded_inside_the_file(self, admin_client, data):
        content, _ = _download(admin_client, {"q": "DDoS"})
        info = load_workbook(io.BytesIO(content))["조건"]
        values = {r[0]: r[1] for r in info.iter_rows(values_only=True)}
        assert values["건수"] == 1
        assert "DDoS" in values["조건(DSL)"]


class TestSafety:
    def test_formula_is_written_as_text_in_xlsx(self, admin_client, data):
        content, _ = _download(admin_client, {"q": "HYPERLINK"})
        ws = load_workbook(io.BytesIO(content))["인수인계"]
        header = [c.value for c in ws[1]]
        cell = ws.cell(row=2, column=header.index("제목") + 1)
        assert cell.data_type == "s", "수식(f)으로 저장되면 여는 순간 실행된다"

    def test_formula_is_neutralized_in_csv(self, admin_client, data):
        content, _ = _download(admin_client, {"q": "HYPERLINK", "format": "csv"})
        assert content.startswith(b"\xef\xbb\xbf"), "Excel 에서 한글이 깨지지 않게 BOM"
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        title = rows[1][rows[0].index("제목")]
        remark = rows[1][rows[0].index("비고")]
        assert title.startswith("'=") and remark.startswith("'@")

    def test_unknown_column_is_rejected(self, admin_client, data):
        assert admin_client.post(EXPORT, json={"columns": ["password_hash"]}).status_code == 422

    def test_over_limit_is_refused_not_truncated(self, admin_client, data, db):
        """잘린 파일을 받은 사람은 그게 전부인 줄 안다. 조용히 자르지 않는다."""
        settings_service.set_value(db, "export.max_rows", 2)
        db.commit()
        resp = admin_client.post(EXPORT, json={})
        assert resp.status_code == 422
        assert resp.json()["detail"] == {"total": 4, "limit": 2}

    def test_invalid_dsl_is_rejected_same_as_search(self, admin_client, data):
        resp = admin_client.post(EXPORT, json={
            "filters": [{"field": "password_hash", "op": "eq", "value": "x"}]})
        assert resp.status_code == 422


class TestDownloadAccess:
    def test_other_user_cannot_download(self, admin_client, data):
        meta = admin_client.post(EXPORT, json={}).json()
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            resp = analyst.get(f"/api/v1/export/download/{meta['download_token']}")
        assert resp.status_code == 404

    @pytest.mark.parametrize("token", ["../../.env", "short", "a" * 100])
    def test_malformed_token_is_404(self, admin_client, token):
        assert admin_client.get(f"/api/v1/export/download/{token}").status_code == 404

    def test_analyst_can_export(self, analyst_client, data):
        assert analyst_client.post(EXPORT, json={}).status_code == 200


class TestAudit:
    def test_export_is_audited_with_conditions(self, admin_client, data, db):
        _download(admin_client, {"q": "DDoS", "format": "csv"})
        log = db.scalar(select(AuditLog).where(AuditLog.action == "EXCEL_EXPORT"))
        assert log is not None
        assert log.detail["rows"] == 1
        assert log.detail["format"] == "csv"
        assert log.detail["dsl"]["q"] == "DDoS"
