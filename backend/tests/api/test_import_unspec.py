"""예약 코드(UNSPEC) 재사용 — 이름이 바뀐 현장 DB 에서도 깨지지 않아야 한다(재현 ⑤).

현장에서 '미지정' 을 '공통' 으로 고쳐 쓰는 일이 있다. 그때 이름으로만 찾고 code='UNSPEC' 로
새로 만들면 고유키(code) 에서 터진다 — 가져오기 전체가 멈춘다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from app.models.handover import Handover
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


class TestCancelAndResume:
    """잘못 올린 작업은 폐기하고, 반영 중이면 배치 경계에서 멈춘다(재현 ⑤).

    멈춘 뒤 다시 반영하면 **이어서** 넣는다 — 같은 행을 두 번 넣지 않는다.
    """

    def _staged(self, client) -> dict:
        job = client.post(JOBS, files={"file": ("인수인계_2025.xlsx", build_workbook(), XLSX)}).json()
        client.post(f"{JOBS}/{job['id']}/mapping", json={
            "sheets": job["options"]["sheets"], "column_mapping": job["column_mapping"],
            "default_status": "DONE"})
        assert client.post(f"{JOBS}/{job['id']}/stage").status_code == 202
        return client.get(f"{JOBS}/{job['id']}").json()

    def test_discard_before_commit_removes_everything(self, admin_client, db):
        from pathlib import Path
        from app.models.importjob import ExcelImportJob, ExcelImportRow
        job = self._staged(admin_client)
        stored = Path(db.get(ExcelImportJob, job["id"]).stored_path)
        assert stored.exists()
        assert db.scalar(select(func.count()).select_from(ExcelImportRow)
                         .where(ExcelImportRow.job_id == job["id"])) > 0

        out = admin_client.post(f"{JOBS}/{job['id']}/cancel")
        assert out.status_code == 200, out.text
        assert out.json()["mode"] == "discarded"

        db.expire_all()
        assert db.get(ExcelImportJob, job["id"]).status == "CANCELED"
        assert db.scalar(select(func.count()).select_from(ExcelImportRow)
                         .where(ExcelImportRow.job_id == job["id"])) == 0, "임시 자료를 지운다"
        assert not stored.exists(), "올린 파일도 지운다"
        assert db.scalar(select(func.count()).select_from(Handover)) == 0, "반영된 것은 없다"

    def test_stopping_mid_commit_keeps_what_went_in_and_resumes(self, admin_client, db, monkeypatch):
        """배치 경계에서 멈춘 뒤 다시 반영하면 남은 것만 들어간다."""
        from app.importers.excel import pipeline
        from app.models.importjob import ExcelImportJob

        job = self._staged(admin_client)
        monkeypatch.setattr(pipeline, "COMMIT_BATCH", 1)      # 한 행씩 — 경계를 만들기 위해

        # 첫 배치를 넣은 뒤 멈추도록, 배치 하나가 끝나면 중단을 요청한다
        original = pipeline.commit_rows
        state = {"stopped": False}

        def commit_with_stop(s, j, who, progress):
            def progress_and_stop(pct):
                if not state["stopped"]:
                    state["stopped"] = True
                    s.execute(update(ExcelImportJob)
                              .where(ExcelImportJob.id == j.id).values(cancel_requested=True))
                    s.commit()
                progress(pct)
            return original(s, j, who, progress_and_stop)

        monkeypatch.setattr(pipeline, "commit_rows", commit_with_stop)
        assert admin_client.post(f"{JOBS}/{job['id']}/commit").status_code == 202
        stopped = admin_client.get(f"{JOBS}/{job['id']}").json()
        assert stopped["status"] == "CANCELED", stopped
        report = stopped["report"]
        partial = db.scalar(select(func.count()).select_from(Handover)) or 0
        expected_total = report["imported"] + report["remaining"]
        assert 0 < partial < expected_total, f"일부만 들어가 있어야 한다(지금 {partial})"
        assert report["canceled"] is True and report["remaining"] > 0

        # 다시 반영 — 멈춘 자리에서 이어서 넣는다
        monkeypatch.setattr(pipeline, "commit_rows", original)
        assert admin_client.post(f"{JOBS}/{job['id']}/commit").status_code == 202
        done = admin_client.get(f"{JOBS}/{job['id']}").json()
        assert done["status"] == "COMPLETED", done
        assert db.scalar(select(func.count()).select_from(Handover)) == expected_total,             "멈췄다 이어서 넣어도 전체 건수는 한 번 넣은 것과 같다(중복 반영 없음)"

        # 한 번 더 눌러도 늘지 않는다(재시도 · 재시작 대비)
        admin_client.post(f"{JOBS}/{job['id']}/commit")
        assert db.scalar(select(func.count()).select_from(Handover)) == expected_total

    def test_report_shows_imported_not_imported_and_modified(self, admin_client, db):
        job = self._staged(admin_client)
        admin_client.post(f"{JOBS}/{job['id']}/commit")
        done = admin_client.get(f"{JOBS}/{job['id']}").json()
        assert done["status"] == "COMPLETED"

        # 반영된 건 하나를 사람이 고친다
        first = db.scalars(select(Handover).order_by(Handover.id)).first()
        resp = admin_client.patch(f"/api/v1/handovers/{first.id}",
                                  json={"expected_version": 1, "content": "현장에서 고침"})
        assert resp.status_code == 200, resp.text

        report = admin_client.get(f"{JOBS}/{job['id']}/report").json()
        assert report["imported"] > 0
        assert report["modified_after_import"] == 1, "되돌리기에서 남길 건수를 미리 보여 준다"
        assert report["not_imported"] == report["total"] - report["imported"] - report["blank"]
        assert report["not_imported"] > 0, "오류 · 중복으로 안 들어간 행이 보인다"

    def test_cannot_discard_after_commit(self, admin_client):
        job = self._staged(admin_client)
        admin_client.post(f"{JOBS}/{job['id']}/commit")
        assert admin_client.get(f"{JOBS}/{job['id']}").json()["status"] == "COMPLETED"
        refused = admin_client.post(f"{JOBS}/{job['id']}/cancel")
        assert refused.status_code == 409, "끝난 작업은 되돌리기(rollback)를 쓴다"
