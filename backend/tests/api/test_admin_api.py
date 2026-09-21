"""Phase 8 — 감사 로그 · 설정 · 인수인계 댓글 · 첨부 · 알림 · 통계.

완료 기준(ARCHITECTURE §10): '감사 30종 기록 검증' — 정의된 35종을 실제 API 로 한 번씩 일으켜
전부 기록되는지, 감사 화면 API 로 다시 찾을 수 있는지 본다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.audit import actions
from app.core.config import settings
from app.core.time import KST, today
from app.main import app
from app.models.common import Attachment, AuditLog, Notification, SystemSetting
from app.models.reference import Company
from app.services import audit_archive_service, audit_service
from tests.conftest import ADMIN_PW, ANALYST_PW, MANAGER_PW, ApiClient
from tests.excel_factory import XLSX, build_workbook

H = "/api/v1/handovers"
A = "/api/v1/attachments"


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    clients = {"admin": _client("admin", ADMIN_PW), "mgr": _client("manager1", MANAGER_PW),
               "hong": _client("analyst1", ANALYST_PW), "kim": _client("analyst2", ANALYST_PW)}
    yield {**clients, "ids": users}
    for c in clients.values():
        c.__exit__(None, None, None)


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _handover(client, cid, title="인수인계", **over) -> dict:
    resp = client.post(H, json={"company_id": cid, "title": title, "content": title,
                                "status_code": "IN_PROGRESS", **over})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _period(days: int = 1) -> dict:
    end = datetime.now(KST) + timedelta(minutes=5)
    return {"start": (end - timedelta(days=days)).isoformat(), "end": end.isoformat()}


def _upload(client, entity_id, name="log.txt", data=b"hello", entity_type="HANDOVER"):
    return client.post(A, data={"entity_type": entity_type, "entity_id": str(entity_id)},
                       files={"file": (name, data, "application/octet-stream")})


# --------------------------------------------------------------------------- 감사 35종

class TestAuditCoverage:
    def test_every_defined_action_is_recorded(self, people, cid, db):
        """정의된 감사 행위 전부(34종)를 실제 API · 배치로 한 번씩 일으킨다(완료 기준: 30종 이상)."""
        admin, mgr, hong = people["admin"], people["mgr"], people["hong"]
        ids = people["ids"]

        # 인증
        ApiClient(app).__enter__().login("analyst1", "wrong-password")                   # LOGIN_FAILURE
        extra = _client("analyst2", ANALYST_PW)                                           # LOGIN_SUCCESS
        extra.post("/api/v1/auth/change-password", json={                                 # PASSWORD_CHANGE
            "current_password": ANALYST_PW, "new_password": "Rotated#Pw2026!qz"})
        admin.post(f"/api/v1/users/{ids['analyst2']['id']}/reset-password")               # PASSWORD_RESET
        bye = _client("manager1", MANAGER_PW)
        bye.post("/api/v1/auth/logout")                                                   # LOGOUT

        # 인수인계
        h = _handover(hong, cid, "감사 확인용", assignee_id=ids["analyst"]["id"])         # CREATE
        hong.post(f"{H}/{h['id']}/view")                                                  # VIEW
        hong.patch(f"{H}/{h['id']}", json={"expected_version": 1, "content": "v2"})      # UPDATE
        mgr.post(f"{H}/{h['id']}/versions/1/restore",                                     # RESTORE
                 json={"expected_version": 2, "change_reason": "되돌림"})
        hong.post(f"{H}/{h['id']}/comments", json={"body": "확인 부탁"})                  # COMMENT
        hong.post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [h["id"]]})
        hong.post("/api/v1/shift-handovers/basket/send",                                  # TRANSFER
                  json={"to_user_ids": [ids["manager"]["id"]]})
        mgr.post(f"{H}/{h['id']}/acknowledge", json={})                                   # ACKNOWLEDGE
        mgr.request("DELETE", f"{H}/{h['id']}", json={"reason": "중복"})                   # DELETE
        admin.post(f"{H}/{h['id']}/undelete")                                             # UNDELETE

        # 할일 · 일정
        t = hong.post("/api/v1/tasks", json={"title": "할일"}).json()                     # TASK_CREATE
        hong.patch(f"/api/v1/tasks/{t['id']}", json={"expected_version": 1, "title": "할일2"})   # TASK_UPDATE
        hong.patch(f"/api/v1/tasks/{t['id']}", json={"expected_version": 2, "status": "DONE"})   # TASK_COMPLETE
        hong.delete(f"/api/v1/tasks/{t['id']}")                                           # TASK_DELETE
        s = hong.post("/api/v1/schedules", json={"title": "점검", "start_at": "2026-10-05T10:00:00+09:00"}).json()
        hong.patch(f"/api/v1/schedules/{s['id']}/move",                                   # CALENDAR_UPDATE
                   json={"expected_version": 1, "start_at": "2026-10-06T10:00:00+09:00"})
        hong.delete(f"/api/v1/schedules/{s['id']}")                                       # CALENDAR_DELETE

        # 데이터 이동
        job = admin.post("/api/v1/import/jobs", files={"file": ("인수인계.xlsx", build_workbook(), XLSX)}).json()
        admin.post(f"/api/v1/import/jobs/{job['id']}/mapping", json={
            "sheets": job["options"]["sheets"], "column_mapping": job["column_mapping"], "default_status": "DONE"})
        admin.post(f"/api/v1/import/jobs/{job['id']}/stage")
        admin.post(f"/api/v1/import/jobs/{job['id']}/commit")                             # EXCEL_IMPORT
        admin.post(f"/api/v1/import/jobs/{job['id']}/rollback")                           # EXCEL_IMPORT_ROLLBACK
        admin.post("/api/v1/export/handovers", json={})                                   # EXCEL_EXPORT
        up = _upload(hong, h["id"])                                                       # ATTACHMENT_UPLOAD
        assert up.status_code == 201, up.text
        att = up.json()
        hong.get(f"{A}/{att['id']}/download")                                             # ATTACHMENT_DOWNLOAD
        hong.delete(f"{A}/{att['id']}")                                                   # ATTACHMENT_DELETE

        # 관리
        u = admin.post("/api/v1/users", json={"username": "newbie", "display_name": "신입",   # USER_CREATE
                                              "password": "Night#Shift2026!zq", "role_code": "ANALYST"}).json()
        admin.patch(f"/api/v1/users/{u['id']}", json={"team": "야간조"})                    # USER_UPDATE
        admin.patch(f"/api/v1/users/{u['id']}", json={"role_code": "MANAGER"})             # ROLE_CHANGE
        admin.patch("/api/v1/settings/export.max_rows", json={"value": 50_000})            # SETTING_CHANGE
        for action in ("BACKUP", "RESTORE"):                                                # 운영 스크립트
            admin.post("/api/v1/audit/system-event", json={"action": action, "detail": {"file": "x.db"}})
        # AUDIT_ARCHIVE — 1년 넘은 감사로그 한 건을 만들어 보관 정리를 돌린다
        db.add(AuditLog(event_uuid="0" * 32, occurred_at=datetime.now(KST) - timedelta(days=400),
                        action="LOGIN_SUCCESS", result="SUCCESS", username="old"))
        db.commit()
        audit_archive_service.archive_expired(db, out_dir=settings.BACKUP_DIR / "audit-archive-test")

        recorded = {a for (a,) in db.execute(select(AuditLog.action).distinct())}
        missing = sorted(set(actions.ALL_ACTIONS) - recorded)
        assert not missing, f"기록되지 않은 감사 행위: {missing}"
        assert len(recorded & set(actions.ALL_ACTIONS)) >= 30

        # 감사 화면 API 로 다시 찾을 수 있다
        found = admin.post("/api/v1/audit/search", json={**_period(), "actions": ["ATTACHMENT_UPLOAD"]}).json()
        assert found["total"] == 1 and found["items"][0]["action_label"] == "첨부 올림"
        fail = admin.post("/api/v1/audit/search", json={**_period(), "result": "FAILURE"}).json()
        assert {i["action"] for i in fail["items"]} >= {"LOGIN_FAILURE"}

    def test_every_action_has_a_label_and_group(self):
        assert set(audit_service.ACTION_LABELS) == set(actions.ALL_ACTIONS)
        grouped = [a for codes in audit_service.ACTION_GROUPS.values() for a in codes]
        assert sorted(grouped) == sorted(actions.ALL_ACTIONS), "필터 묶음에 빠지거나 겹친 행위가 없다"


# --------------------------------------------------------------------------- 감사 조회 · 내보내기

class TestAuditSearch:
    def test_period_is_required_and_bounded(self, people):
        admin = people["admin"]
        assert admin.post("/api/v1/audit/search", json={}).status_code == 422
        too_long = admin.post("/api/v1/audit/search", json=_period(days=120))
        assert too_long.status_code == 422

    def test_analyst_sees_only_own_actions(self, people, cid):
        _handover(people["mgr"], cid, "관리자 등록")
        _handover(people["hong"], cid, "홍길동 등록")
        mine = people["hong"].post("/api/v1/audit/search", json={
            **_period(), "user_id": people["ids"]["manager"]["id"]}).json()
        assert mine["total"] > 0 and {i["username"] for i in mine["items"]} == {"analyst1"}, \
            "다른 사람을 지정해도 자기 기록만"
        everyone = people["mgr"].post("/api/v1/audit/search", json={**_period(), "actions": ["HANDOVER_CREATE"]}).json()
        assert {i["username"] for i in everyone["items"]} == {"manager1", "analyst1"}

    def test_filters_and_paging(self, people, cid):
        for n in range(3):
            _handover(people["hong"], cid, f"건{n}")
        body = people["mgr"].post("/api/v1/audit/search", json={
            **_period(), "username": "analyst1", "actions": ["HANDOVER_CREATE"], "size": 2, "order": "asc"}).json()
        assert body["total"] == 3 and len(body["items"]) == 2
        times = [i["occurred_at"] for i in body["items"]]
        assert times == sorted(times)
        assert people["mgr"].post("/api/v1/audit/search", json={**_period(), "actions": ["NOPE"]}).status_code == 422

    def test_export_is_itself_audited(self, people, cid, db):
        _handover(people["hong"], cid)
        out = people["mgr"].post("/api/v1/audit/export", json=_period()).json()
        assert out["rows"] > 0 and out["file_name"].startswith("감사로그_")
        got = people["mgr"].get(f"/api/v1/export/download/{out['download_token']}")
        assert got.status_code == 200 and got.content[:2] == b"PK"
        assert people["hong"].get(f"/api/v1/export/download/{out['download_token']}").status_code == 404, \
            "요청자 본인만"
        log = db.scalar(select(AuditLog).where(AuditLog.action == "EXCEL_EXPORT", AuditLog.resource_type == "AUDIT"))
        assert log is not None and log.detail["rows"] == out["rows"]

    def test_catalog(self, people):
        body = people["hong"].get("/api/v1/audit/catalog").json()
        assert body["max_range_days"] == 93
        assert any(a["code"] == "LOGIN_FAILURE" and a["label"] == "로그인 실패"
                   for g in body["groups"] for a in g["actions"])


# --------------------------------------------------------------------------- 설정

class TestSettings:
    @pytest.mark.parametrize("key,value", [
        ("retention.audit_days", 100), ("retention.audit_days", "365"), ("export.max_rows", 10),
        ("shift.carry_forward_auto", "yes"), ("attachment.allowed_ext", ["exe"]),
        ("attachment.allowed_ext", ["../x"]), ("ack.reack_fields", ["password"]), ("ack.reack_fields", []),
    ])
    def test_invalid_values_rejected(self, people, key, value):
        assert people["admin"].patch(f"/api/v1/settings/{key}", json={"value": value}).status_code == 422

    def test_unknown_key_and_permission(self, people):
        assert people["admin"].patch("/api/v1/settings/nope.nope", json={"value": 1}).status_code == 404
        assert people["mgr"].patch("/api/v1/settings/export.max_rows", json={"value": 5000}).status_code == 403

    def test_change_is_normalized_and_audited(self, people, db):
        resp = people["admin"].patch("/api/v1/settings/attachment.allowed_ext",
                                     json={"value": ["PDF", ".png", "pdf"]})
        assert resp.json()["value"] == ["pdf", "png"]
        log = db.scalar(select(AuditLog).where(AuditLog.action == "SETTING_CHANGE",
                                               AuditLog.resource_id == "attachment.allowed_ext"))
        assert log.after_value == {"value": ["pdf", "png"]}
        listed = {s["key"]: s for s in people["admin"].get("/api/v1/settings").json()}
        assert listed["retention.audit_days"]["spec"]["min"] == 365
        assert any(c["value"] == "title" for c in listed["ack.reack_fields"]["spec"]["choices"])

    def test_settings_without_row_show_default(self, people, db):
        """설치 뒤에 새로 생긴 설정(행 없음)도 목록에 기본값으로 보이고, 저장하면 행이 생긴다."""
        db.execute(delete(SystemSetting).where(SystemSetting.key == "import.status_aliases"))
        db.commit()
        listed = {s["key"]: s for s in people["admin"].get("/api/v1/settings").json()}
        row = listed["import.status_aliases"]
        assert row["value"] == {} and row["updated_at"] is None and row["spec"]["kind"] == "aliases"
        people["admin"].patch("/api/v1/settings/import.status_aliases", json={"value": {"DONE": ["처리끝"]}})
        assert db.get(SystemSetting, "import.status_aliases").value == {"DONE": ["처리끝"]}

    def test_features_follow_export_limit(self, people):
        people["admin"].patch("/api/v1/settings/export.max_rows", json={"value": 5000})
        assert people["hong"].get("/api/v1/settings/features").json()["export"]["max_rows"] == 5000,             "내보내기 창이 보여주는 상한도 설정값을 따른다"


# --------------------------------------------------------------------------- 댓글

class TestComments:
    def test_comment_lifecycle(self, people, cid, db):
        hong, kim, mgr = people["hong"], people["kim"], people["mgr"]
        h = _handover(hong, cid)
        c = hong.post(f"{H}/{h['id']}/comments", json={"body": "로그 첨부했습니다"}).json()
        assert c["author"] == "홍길동" and c["can_edit"]
        assert kim.patch(f"/api/v1/handover-comments/{c['id']}", json={"body": "x"}).status_code == 403
        edited = hong.patch(f"/api/v1/handover-comments/{c['id']}", json={"body": "로그 2개 첨부"}).json()
        assert edited["is_edited"] and edited["body"] == "로그 2개 첨부"
        line = next(e for e in hong.get(f"{H}/{h['id']}/timeline").json() if e["kind"] == "COMMENT")
        assert line["title"] == "댓글: 로그 2개 첨부", "이력에서 댓글 내용을 한 줄로 보여준다"
        assert kim.delete(f"/api/v1/handover-comments/{c['id']}").status_code == 403
        assert mgr.delete(f"/api/v1/handover-comments/{c['id']}").status_code == 204, "관리자는 지울 수 있다"

        ops = [(l.detail["op"], l.before_value, l.after_value) for l in db.scalars(
            select(AuditLog).where(AuditLog.action == "HANDOVER_COMMENT").order_by(AuditLog.id))]
        assert [o for o, *_ in ops] == ["create", "update", "delete"]
        assert ops[1][1] == {"body": "로그 첨부했습니다"}, "고치기 전 글을 남긴다"
        detail = hong.get(f"{H}/{h['id']}").json()
        assert detail["comment_count"] == 0 and detail["current_version_no"] == 1, "댓글은 버전을 만들지 않는다"


# --------------------------------------------------------------------------- 첨부

class TestAttachments:
    def test_upload_download_delete(self, people, cid, db):
        hong = people["hong"]
        h = _handover(hong, cid)
        up = _upload(hong, h["id"], name="../../방화벽 로그.txt", data=b"deny tcp 10.0.0.1")
        assert up.status_code == 201, up.text
        att = up.json()
        assert att["name"] == "방화벽 로그.txt", "경로 부분은 떼어 낸다"
        assert att["size"] == 17 and len(att["sha256"]) == 64 and att["scan_status"] == "NOT_SCANNED"

        row = db.get(Attachment, att["id"])
        stored = settings.attachments_dir / row.rel_path
        assert stored.exists() and "." not in stored.name, "확장자 없이 무작위 이름으로 저장"

        got = hong.get(f"{A}/{att['id']}/download")
        assert got.content == b"deny tcp 10.0.0.1"
        assert got.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
        assert got.headers["x-content-type-options"] == "nosniff"

        assert hong.get(f"{H}/{h['id']}").json()["attachment_count"] == 1
        assert any(e["kind"] == "ATTACHMENT" for e in hong.get(f"{H}/{h['id']}/timeline").json())
        assert people["kim"].delete(f"{A}/{att['id']}").status_code == 403
        assert hong.delete(f"{A}/{att['id']}").status_code == 204
        assert stored.exists(), "지워도 파일은 증적으로 남긴다"
        assert hong.get(f"{A}/{att['id']}/download").status_code == 404

    @pytest.mark.parametrize("name", ["run.exe", "x.ps1", "page.html", "noext"])
    def test_blocked_or_unlisted_extensions(self, people, cid, name):
        h = _handover(people["hong"], cid)
        assert _upload(people["hong"], h["id"], name=name).status_code == 422

    def test_size_limit_and_empty(self, people, cid, db):
        from app.services import settings_service
        settings_service.set_value(db, "attachment.max_size_mb", 1)
        db.commit()
        h = _handover(people["hong"], cid)
        before = {p for p in settings.attachments_dir.rglob("*") if p.is_file()}
        assert _upload(people["hong"], h["id"], data=b"x" * (1024 * 1024 + 1)).status_code == 422
        assert _upload(people["hong"], h["id"], data=b"").status_code == 422
        after = {p for p in settings.attachments_dir.rglob("*") if p.is_file()}
        assert after == before, "거절한 파일은 저장소에 남지 않는다"

    def test_only_editors_can_upload(self, people, cid):
        h = _handover(people["hong"], cid)
        assert _upload(people["kim"], h["id"]).status_code == 403
        assert _upload(people["mgr"], h["id"]).status_code == 201

    def test_task_attachment(self, people):
        t = people["hong"].post("/api/v1/tasks", json={"title": "할일"}).json()
        assert _upload(people["hong"], t["id"], entity_type="TASK").status_code == 201
        listed = people["kim"].get(A, params={"entity_type": "TASK", "entity_id": t["id"]}).json()
        assert [a["name"] for a in listed] == ["log.txt"] and not listed[0]["can_delete"]

    def test_scanner_hook(self, people, cid, monkeypatch):
        import sys
        h = _handover(people["hong"], cid)
        monkeypatch.setattr(settings, "ATTACHMENT_SCAN_COMMAND", f'"{sys.executable}" -c "import sys; sys.exit(0)" {{path}}')
        assert _upload(people["hong"], h["id"]).json()["scan_status"] == "CLEAN"
        monkeypatch.setattr(settings, "ATTACHMENT_SCAN_COMMAND", f'"{sys.executable}" -c "import sys; sys.exit(3)" {{path}}')
        bad = _upload(people["hong"], h["id"], name="bad.txt")
        assert bad.status_code == 422 and "위험" in bad.json()["message"]
        monkeypatch.setattr(settings, "ATTACHMENT_SCAN_COMMAND", "no-such-scanner-xyz {path}")
        assert _upload(people["hong"], h["id"]).status_code == 422, "검사를 못 하면 올리지 않는다"

    def test_tampered_path_is_refused(self, people, cid, db):
        h = _handover(people["hong"], cid)
        att = _upload(people["hong"], h["id"]).json()
        row = db.get(Attachment, att["id"])
        row.rel_path = "../../test.db"
        db.commit()
        assert people["hong"].get(f"{A}/{att['id']}/download").status_code == 404


# --------------------------------------------------------------------------- 알림

class TestNotifications:
    def _types(self, db, user_id):
        return [n.type for n in db.scalars(select(Notification).where(Notification.user_id == user_id)
                                           .order_by(Notification.id))]

    def test_assigned_and_important(self, people, cid, db):
        ids = people["ids"]
        h = _handover(people["hong"], cid, "담당 지정", assignee_id=ids["analyst2"]["id"])
        assert self._types(db, ids["analyst2"]["id"]) == ["HANDOVER_ASSIGNED"]
        people["hong"].patch(f"{H}/{h['id']}", json={"expected_version": 1, "is_important": True})
        for who in ("manager", "admin"):
            assert "IMPORTANT_HANDOVER" in self._types(db, ids[who]["id"])
        assert "IMPORTANT_HANDOVER" not in self._types(db, ids["analyst"]["id"]), "지정한 본인에게는 보내지 않는다"

    def test_due_soon_and_overdue_once_a_day(self, people, db):
        from app.jobs import reminders
        hong_id = people["ids"]["analyst"]["id"]
        t0 = today()
        people["hong"].post("/api/v1/tasks", json={"title": "오늘 마감", "due_date": t0.isoformat()})
        people["hong"].post("/api/v1/tasks", json={"title": "지난 마감", "due_date": (t0 - timedelta(days=2)).isoformat()})
        people["hong"].post("/api/v1/tasks", json={"title": "다음 주", "due_date": (t0 + timedelta(days=7)).isoformat()})
        assert reminders.run(db) == {"due_soon": 1, "overdue": 1}
        db.commit()
        people["hong"].post("/api/v1/notifications/read-all")
        assert reminders.run(db) == {"due_soon": 0, "overdue": 0}, "읽은 뒤에도 같은 날 다시 보내지 않는다"
        tomorrow = datetime.now(KST) + timedelta(days=1)
        assert reminders.run(db, at=tomorrow)["overdue"] == 2, "다음 날에는 다시(오늘 마감도 지연이 된다)"
        assert set(self._types(db, hong_id)) == {"TASK_DUE_SOON", "TASK_OVERDUE"}


# --------------------------------------------------------------------------- 통계

class TestStats:
    def test_summary(self, people, cid, db):
        hong, mgr = people["hong"], people["mgr"]
        a = _handover(hong, cid, "A", registered_date=today().isoformat())
        _handover(hong, cid, "B", registered_date=today().isoformat(), status_code="DONE")
        hong.post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [a["id"]]})
        hong.post("/api/v1/shift-handovers/basket/send", json={"to_user_ids": [people["ids"]["manager"]["id"]]})
        mgr.post(f"{H}/{a['id']}/acknowledge", json={})
        body = mgr.get("/api/v1/stats/summary").json()
        assert body["total"] == 2
        assert body["by_company"][0]["open"] == 1 and body["by_company"][0]["closed"] == 1
        assert body["ack"]["items"] == 1 and body["ack"]["acked"] == 1 and body["ack"]["rate"] == 100.0
        assert sum(m["count"] for m in body["by_month"]) == 2

    def test_permission_and_range(self, people):
        assert people["hong"].get("/api/v1/stats/summary").status_code == 403
        assert people["mgr"].get("/api/v1/stats/summary", params={"start": "2025-01-01", "end": "2026-06-01"}).status_code == 422



class TestBackups:
    def test_listing_is_admin_only(self, people):
        settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (settings.BACKUP_DIR / "soc_handover_20260919_120000.db").write_bytes(b"x" * 10)
        (settings.BACKUP_DIR / "notes.txt").write_text("무시")
        body = people["admin"].get("/api/v1/backups").json()
        assert [f["name"] for f in body["files"]][:1] == ["soc_handover_20260919_120000.db"]
        assert all(not f["name"].endswith(".txt") for f in body["files"])
        assert body["stale"] is False and body["hours_since_latest"] < 1
        assert people["mgr"].get("/api/v1/backups").status_code == 403
