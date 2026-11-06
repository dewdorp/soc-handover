"""운영 편의성 패치: 공개 범위, 감사 소음, 지식 문서, 금고 단기 열람."""
from __future__ import annotations

from sqlalchemy import select

from app.audit import actions
from app.main import app
from app.models.common import AuditLog, SystemSetting
from app.models.group import Group, UserGroup
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient


def _login(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


def _company_id(db):
    from app.models.reference import Company
    return db.scalar(select(Company.id).limit(1))


def test_ungrouped_handover_public_and_explicit_group_restricted(users, db):
    admin = _login("admin", ADMIN_PW)
    other = _login("analyst1", ANALYST_PW)
    try:
        cid = _company_id(db)
        new = admin.post("/api/v1/handovers",
                         json={"company_id":cid,"title":"공통 교대 참고","content":"전체 공유"})
        assert new.status_code == 201, new.text
        row = new.json()
        assert row["visibility"] == "ALL"
        assert other.get(f"/api/v1/handovers/{row['id']}").status_code == 200

        group = Group(name="운영 패치 검증 내부 그룹", is_active=True)
        db.add(group)
        db.flush()
        db.add(UserGroup(user_id=users["admin"]["id"], group_id=group.id, is_default=False))
        db.commit()
        locked = admin.post("/api/v1/handovers",
            json={"company_id":cid,"title":"내부 전용 대응","content":"그룹 제한",
                  "visibility":"GROUPS","group_ids":[group.id]})
        assert locked.status_code == 201, locked.text
        assert other.get(f"/api/v1/handovers/{locked.json()['id']}").status_code == 404
    finally:
        admin.__exit__(None,None,None)
        other.__exit__(None,None,None)


def test_handover_view_audit_optional(users, db):
    admin = _login("admin", ADMIN_PW)
    try:
        cid = _company_id(db)
        r = admin.post("/api/v1/handovers",json={"company_id":cid,"title":"감사검사"})
        assert r.status_code == 201, r.text
        hid = r.json()["id"]
        assert admin.post(f"/api/v1/handovers/{hid}/view").status_code == 204
        assert not db.scalars(select(AuditLog).where(
            AuditLog.action == actions.HANDOVER_VIEW)).all()
        row = db.get(SystemSetting, "audit.track_handover_views")
        row.value = True
        db.commit()
        assert admin.get(f"/api/v1/handovers/{hid}").status_code == 200
        db.expire_all()
        assert len(db.scalars(select(AuditLog).where(
            AuditLog.action == actions.HANDOVER_VIEW)).all()) == 1
    finally:
        admin.__exit__(None,None,None)


def test_knowledge_article_groups_and_file_download(users, db):
    admin = _login("admin", ADMIN_PW)
    other = _login("analyst1", ANALYST_PW)
    try:
        public = admin.post("/api/v1/knowledge",
             json={"category":"운영 절차", "title":"야간 관제 SOP",
                   "body":"확인→조치→인계"})
        assert public.status_code == 201, public.text
        pubid = public.json()["id"]
        assert other.get(f"/api/v1/knowledge/{pubid}").status_code == 200
        files = {"file":("sop.pdf",b"%PDF-1.4\nSOC runbook\n%%EOF","application/pdf")}
        saved = admin.post("/api/v1/attachments",
            data={"entity_type":"KNOWLEDGE","entity_id":str(pubid)},files=files)
        assert saved.status_code == 201, saved.text
        aid = saved.json()["id"]
        assert other.get(f"/api/v1/attachments/{aid}/download").status_code == 200

        group = Group(name="CERT 내부 운영 절차", is_active=True)
        db.add(group)
        db.flush()
        db.add(UserGroup(user_id=users["admin"]["id"], group_id=group.id, is_default=False))
        db.commit()
        private = admin.post("/api/v1/knowledge",
             json={"category":"참고 자료", "title":"비공개 긴급 절차",
                   "body":"권한 제한", "visibility":"GROUPS","group_ids":[group.id]})
        assert private.status_code == 201, private.text
        private_id = private.json()["id"]
        assert other.get(f"/api/v1/knowledge/{private_id}").status_code == 404
        assert all(x["id"]!=private_id for x in other.get("/api/v1/knowledge").json())
        # 직접 URL·첨부 번호를 알아도 접근할 수 없어야 한다.
        files2 = {"file":("secret.pdf",b"%PDF-1.4\nPRIVATE\n%%EOF","application/pdf")}
        result2 = admin.post("/api/v1/attachments",
            data={"entity_type":"KNOWLEDGE","entity_id":str(private_id)},files=files2)
        assert result2.status_code == 201, result2.text
        assert other.get(f"/api/v1/attachments/{result2.json()['id']}/download").status_code == 404
    finally:
        admin.__exit__(None,None,None)
        other.__exit__(None,None,None)


def test_bulk_vault_unlock_restricts_personal_and_locks(users, db):
    admin = _login("admin", ADMIN_PW)
    analyst = _login("analyst1", ANALYST_PW)
    try:
        cid = _company_id(db)
        personal = admin.post("/api/v1/credentials",
            json={"company_id":cid,"device_name":"내 전용 계정","scope":"PERSONAL",
                  "username":"alice","secret":"private-secret-2026!"})
        assert personal.status_code == 201, personal.text
        sid = personal.json()["id"]
        shared = analyst.post("/api/v1/credentials",
            json={"company_id":cid,"device_name":"공동 장비","scope":"SHARED",
                  "username":"socadmin","secret":"shared-secret-2026!"})
        assert shared.status_code == 201, shared.text
        hid = shared.json()["id"]
        assert "private-secret-2026!" not in admin.get("/api/v1/credentials").text

        denied = analyst.post("/api/v1/credentials/vault/unlock",json={"password":"wrong"})
        assert denied.status_code == 403
        unlocked = analyst.post("/api/v1/credentials/vault/unlock",json={"password":ANALYST_PW})
        assert unlocked.status_code == 200, unlocked.text
        token = unlocked.json()["token"]
        headers = {"X-Vault-Token":token}
        exposed = analyst.get(f"/api/v1/credentials/vault/secrets?ids={hid}",headers=headers)
        assert exposed.status_code == 200, exposed.text
        assert exposed.json()[0]["secret"] == "shared-secret-2026!"
        assert analyst.get(f"/api/v1/credentials/vault/secrets?ids={sid}",headers=headers).status_code == 404
        assert analyst.post("/api/v1/credentials/vault/extend",headers=headers).status_code == 200
        assert analyst.post("/api/v1/credentials/vault/lock",headers=headers).status_code == 204
        assert analyst.get(f"/api/v1/credentials/vault/secrets?ids={hid}",headers=headers).status_code == 403
        db.expire_all()
        codes = {x for (x,) in db.execute(select(AuditLog.action))}
        assert actions.CREDENTIAL_VAULT_UNLOCK in codes
        assert actions.CREDENTIAL_VAULT_BATCH_REVEAL in codes
        assert actions.CREDENTIAL_VAULT_DENIED in codes
    finally:
        admin.__exit__(None,None,None)
        analyst.__exit__(None,None,None)
