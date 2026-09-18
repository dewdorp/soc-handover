"""Excel Import 8단계 통합 테스트 — 실제 xlsx 를 만들어 실제 API 로 흘린다.

TestClient 는 BackgroundTasks 를 응답 전에 끝까지 실행하므로, 202 를 받은 직후
GET 으로 보면 작업이 이미 끝나 있다. 운영에서는 같은 흐름을 폴링으로 본다.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.main import app
from app.models.common import AuditLog
from app.models.handover import Handover, HandoverVersion
from app.models.reference import Company
from tests.conftest import ANALYST_PW, MANAGER_PW, ApiClient
from tests.excel_factory import XLSX, build_workbook

JOBS = "/api/v1/import/jobs"


@pytest.fixture
def companies(db):
    for name in ("A보안", "B금융"):
        db.add(Company(name=name))
    db.commit()


def _upload(client, content: bytes = None, name: str = "인수인계_2024-2025.xlsx"):
    content = content if content is not None else build_workbook()
    return client.post(JOBS, files={"file": (name, content, XLSX)})


def _mapped(client, content: bytes | None = None) -> dict:
    job = _upload(client, content).json()
    resp = client.post(f"{JOBS}/{job['id']}/mapping", json={
        "sheets": job["options"]["sheets"],
        "column_mapping": job["column_mapping"],
        "default_status": "DONE",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _staged(client, content: bytes | None = None) -> dict:
    job = _mapped(client, content)
    resp = client.post(f"{JOBS}/{job['id']}/stage")
    assert resp.status_code == 202, resp.text
    done = client.get(f"{JOBS}/{job['id']}").json()
    assert done["status"] == "DEDUPED", done
    return done


def _report(client, job_id) -> dict:
    return client.get(f"{JOBS}/{job_id}/report").json()


# --------------------------------------------------------------------------- ① ② 업로드 · 분석

class TestUploadAndAnalyze:
    def test_upload_analyzes_sheets(self, admin_client, companies):
        resp = _upload(admin_client)
        assert resp.status_code == 201, resp.text
        job = resp.json()
        assert job["status"] == "ANALYZED"
        sheets = {s["name"]: s for s in job["sheet_summary"]["sheets"]}
        assert sheets["2025"]["header_row"] == 3, "제목 배너·빈 줄 아래의 헤더를 찾아야 한다"
        assert sheets["2024년"]["header_row"] == 1
        assert sheets["안내"]["recognized"] < 2

    def test_notes_sheet_is_not_selected_by_default(self, admin_client, companies):
        job = _upload(admin_client).json()
        assert job["options"]["sheets"] == ["2025", "2024년"]

    def test_mapping_is_suggested(self, admin_client, companies):
        mapping = _upload(admin_client).json()["column_mapping"]
        assert mapping["진행 상황"] == "status"
        assert mapping["진행상황"] == "status", "Sheet 마다 표기가 달라도 연결돼야 한다"
        assert mapping["전달자/확인자"] == "sender_checker"
        assert mapping["담당부서"] is None, "모르는 컬럼은 원본 보존으로 남긴다"

    def test_non_excel_extension_rejected(self, admin_client):
        resp = admin_client.post(JOBS, files={"file": ("memo.txt", b"hello", "text/plain")})
        assert resp.status_code == 422

    def test_fake_xlsx_rejected_by_content(self, admin_client):
        resp = _upload(admin_client, b"this is not a zip file", "fake.xlsx")
        assert resp.status_code == 422
        assert "Excel 파일이 아닙니다" in resp.json()["message"]

    def test_old_xls_gets_actionable_message(self, admin_client):
        resp = _upload(admin_client, b"\xd0\xcf\x11\xe0" + b"\0" * 100, "old.xls")
        assert resp.status_code == 422
        assert "xlsx" in resp.json()["message"]

    def test_analyst_cannot_import(self, analyst_client):
        assert _upload(analyst_client).status_code == 403


# --------------------------------------------------------------------------- ③ 매핑

class TestMapping:
    def test_same_field_twice_in_one_sheet_is_rejected(self, admin_client, companies):
        job = _upload(admin_client).json()
        mapping = dict(job["column_mapping"])
        mapping["비고"] = "content"  # 2025 Sheet 에서 '내용' 과 겹친다
        resp = admin_client.post(f"{JOBS}/{job['id']}/mapping", json={
            "sheets": ["2025"], "column_mapping": mapping})
        assert resp.status_code == 422

    def test_content_or_title_is_required(self, admin_client, companies):
        job = _upload(admin_client).json()
        mapping = {k: (None if v == "content" else v) for k, v in job["column_mapping"].items()}
        resp = admin_client.post(f"{JOBS}/{job['id']}/mapping", json={
            "sheets": ["2025"], "column_mapping": mapping})
        assert resp.status_code == 422

    def test_stage_before_mapping_is_conflict(self, admin_client, companies):
        job = _upload(admin_client).json()
        assert admin_client.post(f"{JOBS}/{job['id']}/stage").status_code == 409


# --------------------------------------------------------------------------- ④⑤⑥ 적재 · 검증 · 중복

class TestPrepare:
    def test_counts_after_stage(self, admin_client, companies):
        job = _staged(admin_client)
        report = _report(admin_client, job["id"])
        assert report["total"] == 9, "빈 행을 뺀 9행이 적재돼야 한다"
        assert report["blank"] == 1, "빈 행은 사라지지 않고 건수로 남는다"
        assert report["error"] == 2
        assert report["duplicate_batch"] == 1
        assert report["will_import"] == 6

    def test_errors_are_listed_with_source_row(self, admin_client, companies):
        job = _staged(admin_client)
        errors = admin_client.get(f"{JOBS}/{job['id']}/errors").json()["items"]
        found = {(e["source_row"], e["error_code"]) for e in errors}
        assert found == {(10, "DATE_INVALID"), (11, "EMPTY_CONTENT")}

    def test_repeated_row_is_flagged_not_deleted(self, admin_client, companies):
        job = _staged(admin_client)
        dups = admin_client.get(f"{JOBS}/{job['id']}/duplicates").json()["items"]
        assert [(d["source_row"], d["dup_type"], d["will_import"]) for d in dups] \
            == [(9, "BATCH", False)]

    def test_raw_is_kept_exactly(self, admin_client, companies):
        job = _staged(admin_client)
        rows = admin_client.get(f"{JOBS}/{job['id']}/rows?sheet=2025").json()["items"]
        first = rows[0]
        assert first["raw"]["담당부서"] == "보안팀"
        assert first["normalized"]["extra"] == {"담당부서": "보안팀"}

    def test_dates_people_and_inference(self, admin_client, companies, users):
        job = _staged(admin_client)
        rows = {r["source_row"]: r for r in
                admin_client.get(f"{JOBS}/{job['id']}/rows?sheet=2025").json()["items"]}
        r4 = rows[4]["normalized"]
        assert (r4["registered_date"], r4["work_date"]) == ("2025-03-02", "2025-03-04")
        assert r4["date_inferred"] is True, "'3/4' 의 연도는 Sheet 이름에서 빌려왔다"
        assert (r4["sender_name_raw"], r4["checker_name_raw"]) == ("홍길동", "김철수")
        assert r4["sender_id"] == users["analyst"]["id"]
        assert rows[7]["normalized"]["registered_date"] == "2025-03-04", "엑셀 일련번호"

    def test_value_stats_show_what_needs_mapping(self, admin_client, companies):
        job = _staged(admin_client)
        companies_ = admin_client.get(f"{JOBS}/{job['id']}/values?field=company").json()
        unmatched = [c["value"] for c in companies_ if not c["matched"]]
        assert unmatched == ["신규업체"]
        statuses = admin_client.get(f"{JOBS}/{job['id']}/values?field=status").json()
        assert [s["value"] for s in statuses if not s["matched"]] == ["보류됨"]

    def test_value_map_fixes_warnings_and_reprepares(self, admin_client, companies):
        job = _staged(admin_client)
        resp = admin_client.post(f"{JOBS}/{job['id']}/value-map",
                                 json={"field": "status", "mapping": {"보류됨": "HOLD"}})
        assert resp.status_code == 202
        statuses = admin_client.get(f"{JOBS}/{job['id']}/values?field=status").json()
        assert all(s["matched"] for s in statuses)
        rows = admin_client.get(f"{JOBS}/{job['id']}/rows?sheet=2025").json()["items"]
        assert next(r for r in rows if r["source_row"] == 7)["normalized"]["status_code"] == "HOLD"

    def test_value_map_rejects_unknown_target(self, admin_client, companies):
        job = _staged(admin_client)
        resp = admin_client.post(f"{JOBS}/{job['id']}/value-map",
                                 json={"field": "status", "mapping": {"보류됨": "NOPE"}})
        assert resp.status_code == 422

    def test_user_decision_survives_reprepare(self, admin_client, companies):
        """값 매핑을 고쳐 다시 돌렸다고 사람이 고른 것이 사라지면 안 된다."""
        job = _staged(admin_client)
        dup = admin_client.get(f"{JOBS}/{job['id']}/duplicates").json()["items"][0]
        admin_client.patch(f"{JOBS}/{job['id']}/decisions",
                           json={"row_ids": [dup["id"]], "decision": "IMPORT"})
        assert _report(admin_client, job["id"])["will_import"] == 7

        admin_client.post(f"{JOBS}/{job['id']}/value-map",
                          json={"field": "status", "mapping": {"보류됨": "HOLD"}})
        assert _report(admin_client, job["id"])["will_import"] == 7

    def test_error_rows_cannot_be_forced_in(self, admin_client, companies):
        job = _staged(admin_client)
        err = admin_client.get(f"{JOBS}/{job['id']}/rows?kind=error").json()["items"]
        admin_client.patch(f"{JOBS}/{job['id']}/decisions",
                           json={"row_ids": [e["id"] for e in err], "decision": "IMPORT"})
        assert _report(admin_client, job["id"])["will_import"] == 6

    def test_errors_workbook_downloads(self, admin_client, companies):
        job = _staged(admin_client)
        resp = admin_client.get(f"{JOBS}/{job['id']}/errors.xlsx")
        assert resp.status_code == 200
        ws = load_workbook(io.BytesIO(resp.content)).active
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0][:4] == ("Sheet", "행 번호", "오류 코드", "오류 내용")
        assert {r[2] for r in rows[1:]} == {"DATE_INVALID", "EMPTY_CONTENT"}
        assert "관계사" in rows[0], "고쳐서 다시 올릴 수 있게 원본 컬럼도 싣는다"


# --------------------------------------------------------------------------- ⑦ 반영

class TestCommit:
    def _commit(self, client, companies_value_map=None, content: bytes | None = None) -> dict:
        job = _staged(client, content)
        if companies_value_map:
            client.post(f"{JOBS}/{job['id']}/value-map",
                        json={"field": "company", "mapping": companies_value_map})
        resp = client.post(f"{JOBS}/{job['id']}/commit")
        assert resp.status_code == 202, resp.text
        done = client.get(f"{JOBS}/{job['id']}").json()
        assert done["status"] == "COMPLETED", done
        return done

    def test_commit_imports_only_selected_rows(self, admin_client, companies, db):
        job = self._commit(admin_client)
        assert job["success_rows"] == 6
        count = db.scalar(select(func.count()).select_from(Handover)
                          .where(Handover.import_job_id == job["id"]))
        assert count == 6

    def test_each_row_gets_an_import_version(self, admin_client, companies, db):
        job = self._commit(admin_client)
        versions = db.scalars(
            select(HandoverVersion).join(Handover, Handover.id == HandoverVersion.handover_id)
            .where(Handover.import_job_id == job["id"])).all()
        assert len(versions) == 6
        assert {v.change_type for v in versions} == {"IMPORT"}
        assert all(job["job_code"] in v.change_reason for v in versions)

    def test_source_is_traceable(self, admin_client, companies, db):
        job = self._commit(admin_client)
        h = db.scalar(select(Handover).where(Handover.import_job_id == job["id"],
                                             Handover.source_row == 5))
        assert (h.source_sheet, h.title) == ("2025", "EDR 경고 조사")
        assert h.source_file == "인수인계_2024-2025.xlsx"

    def test_unmatched_company_keeps_its_name(self, admin_client, companies, db):
        job = self._commit(admin_client)
        h = db.scalar(select(Handover).where(Handover.import_job_id == job["id"],
                                             Handover.source_row == 6))
        assert h.company.name == "미지정"
        assert "[원본 관계사: 신규업체]" in (h.remark or "")

    def test_company_can_be_created_by_value_map(self, admin_client, companies, db):
        job = self._commit(admin_client, companies_value_map={"신규업체": "__CREATE__"})
        h = db.scalar(select(Handover).where(Handover.import_job_id == job["id"],
                                             Handover.source_row == 6))
        assert h.company.name == "신규업체"

    def test_imported_rows_are_searchable(self, admin_client, companies):
        self._commit(admin_client)
        body = admin_client.post("/api/v1/handovers/search", json={"q": "EDR"}).json()
        assert [i["title"] for i in body["items"]] == ["EDR 경고 조사"]

    def test_commit_is_audited_once(self, admin_client, companies, db):
        job = self._commit(admin_client)
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "EXCEL_IMPORT")).all()
        assert len(logs) == 1, "행 단위가 아니라 job 단위 1건(감사 폭증 방지)"
        assert logs[0].resource_id == job["job_code"]
        assert logs[0].detail["imported"] == 6

    def test_second_commit_is_refused(self, admin_client, companies, db):
        """커밋을 두 번 눌러도 두 벌이 들어가면 안 된다."""
        job = self._commit(admin_client)
        assert admin_client.post(f"{JOBS}/{job['id']}/commit").status_code == 409

    def test_reimporting_same_file_flags_everything(self, admin_client, companies):
        # 같은 '바이트'여야 같은 파일이다. openpyxl 은 저장 시각을 파일에 넣으므로
        # build_workbook() 을 두 번 부르면 초가 바뀔 때 내용이 달라진다.
        content = build_workbook()
        self._commit(admin_client, content=content)
        again = _upload(admin_client, content).json()
        assert again["sheet_summary"]["warnings"], "같은 파일이면 업로드 단계에서 알려준다"
        admin_client.post(f"{JOBS}/{again['id']}/mapping", json={
            "sheets": again["options"]["sheets"], "column_mapping": again["column_mapping"]})
        admin_client.post(f"{JOBS}/{again['id']}/stage")
        report = _report(admin_client, again["id"])
        # 오류가 아닌 7행 전부가 이미 들어간 것과 겹친다(파일 안에서 반복된 9행도 포함).
        assert report["duplicate_existing"] == 7
        assert report["will_import"] == 0, "같은 파일을 두 번 올려도 두 벌이 되지 않는다"

    def test_ui_entered_handover_is_recognized(self, admin_client, companies, db):
        """UI 로 먼저 등록한 건도 같은 지문을 가져야 Excel 과 겹치는지 안다."""
        cid = db.scalar(select(Company.id).where(Company.name == "B금융"))
        admin_client.post("/api/v1/handovers", json={
            "company_id": cid, "title": "EDR 경고 조사", "content": "EDR 경고 조사",
            "registered_date": "2025-03-05", "sender_name_raw": "김철수"})
        job = _staged(admin_client)
        dups = admin_client.get(f"{JOBS}/{job['id']}/duplicates").json()["items"]
        assert (5, "EXISTING") in {(d["source_row"], d["dup_type"]) for d in dups}


# --------------------------------------------------------------------------- 롤백

class TestRollback:
    def test_only_admin_can_rollback(self, manager_client, companies):
        job = _staged(manager_client)
        manager_client.post(f"{JOBS}/{job['id']}/commit")
        assert manager_client.post(f"{JOBS}/{job['id']}/rollback").status_code == 403

    def test_rollback_soft_deletes_but_keeps_edited_rows(self, admin_client, companies, db):
        job = _staged(admin_client)
        admin_client.post(f"{JOBS}/{job['id']}/commit")
        edited = db.scalar(select(Handover).where(Handover.import_job_id == job["id"],
                                                  Handover.source_row == 5))
        admin_client.patch(f"/api/v1/handovers/{edited.id}",
                           json={"expected_version": 1, "status_code": "DONE"})

        assert admin_client.post(f"{JOBS}/{job['id']}/rollback").status_code == 202
        after = admin_client.get(f"{JOBS}/{job['id']}").json()
        assert after["status"] == "ROLLED_BACK"
        assert after["report"]["rollback"] == {"removed": 5, "kept_modified": 1}

        db.expire_all()
        alive = db.scalars(select(Handover).where(Handover.import_job_id == job["id"],
                                                  Handover.is_deleted.is_(False))).all()
        assert [h.id for h in alive] == [edited.id], "Import 뒤에 고친 건은 지우지 않는다"

    def test_rollback_is_audited_as_critical(self, admin_client, companies, db):
        job = _staged(admin_client)
        admin_client.post(f"{JOBS}/{job['id']}/commit")
        admin_client.post(f"{JOBS}/{job['id']}/rollback")
        logs = db.scalars(select(AuditLog).where(
            AuditLog.action == "EXCEL_IMPORT_ROLLBACK")).all()
        assert len(logs) == 1


# --------------------------------------------------------------------------- 복구

class TestRecovery:
    def test_stale_running_job_is_marked_failed_on_startup(self, admin_client, companies, db):
        from app.models.importjob import ExcelImportJob

        job = _mapped(admin_client)
        row = db.get(ExcelImportJob, job["id"])
        row.status, row.phase = "RUNNING", "STAGE"
        db.commit()

        with ApiClient(app):  # 기동(lifespan)이 다시 돈다
            pass
        db.expire_all()
        recovered = db.get(ExcelImportJob, job["id"])
        assert recovered.status == "FAILED"
        assert recovered.phase == "STAGE", "어디서 멈췄는지는 남긴다"

        # 같은 단계는 다시 실행할 수 있다
        assert admin_client.post(f"{JOBS}/{job['id']}/stage").status_code == 202
        assert admin_client.get(f"{JOBS}/{job['id']}").json()["status"] == "DEDUPED"
