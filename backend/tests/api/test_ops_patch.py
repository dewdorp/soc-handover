"""1.3.1 운영 편의성 패치 — 공개 범위 · 감사 소음 · 운영 지식 · 금고 단기 열람.

여기서 지키는 선
  · 그룹을 명시한 자료는 전파 · 직접 URL · 검색 · 첨부 · 내보내기로도 새지 않는다.
  · 과거 자료는 **관리자가 승인할 때만** 전체 공개가 된다.
  · 남의 개인 비밀번호는 일괄 열람으로도 보이지 않는다.
  · 열람 세션은 서버가 수명을 판정하고, 권한이 바뀌면 그 자리에서 끊긴다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit import actions
from app.main import app
from app.models.common import AuditLog, SystemSetting
from app.models.group import Group, UserGroup
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient

K = "/api/v1/knowledge"
H = "/api/v1/handovers"
C = "/api/v1/credentials"
G = "/api/v1/groups"


def _login(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def admin(users):
    c = _login("admin", ADMIN_PW)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def other(users):
    c = _login("analyst1", ANALYST_PW)
    yield c
    c.__exit__(None, None, None)


def _company_id(db):
    from app.models.reference import Company
    return db.scalar(select(Company.id).limit(1))


def _group(db, users, name, *, member="admin") -> int:
    group = Group(name=name, is_active=True)
    db.add(group)
    db.flush()
    db.add(UserGroup(user_id=users[member]["id"], group_id=group.id, is_default=False))
    db.commit()
    return group.id


# --------------------------------------------------------------------------- §3 공개 범위

def test_ungrouped_handover_public_and_explicit_group_restricted(admin, other, users, db):
    cid = _company_id(db)
    new = admin.post(H, json={"company_id": cid, "title": "공통 교대 참고", "content": "전체 공유"})
    assert new.status_code == 201, new.text
    row = new.json()
    assert row["visibility"] == "ALL"
    assert other.get(f"{H}/{row['id']}").status_code == 200

    gid = _group(db, users, "운영 패치 검증 내부 그룹")
    locked = admin.post(H, json={"company_id": cid, "title": "내부 전용 대응", "content": "그룹 제한",
                                 "visibility": "GROUPS", "group_ids": [gid]})
    assert locked.status_code == 201, locked.text
    assert other.get(f"{H}/{locked.json()['id']}").status_code == 404


def test_empty_group_list_cannot_silently_publish_a_restricted_handover(admin, db, users):
    """그룹 제한을 걸어 둔 글에 빈 목록만 보내서 조용히 전체 공개로 넓힐 수 없다."""
    cid = _company_id(db)
    gid = _group(db, users, "조용한 확대 방지 그룹")
    row = admin.post(H, json={"company_id": cid, "title": "제한된 글", "content": "본문",
                              "visibility": "GROUPS", "group_ids": [gid]}).json()
    sneaky = admin.patch(f"{H}/{row['id']}", json={"expected_version": 1, "group_ids": []})
    assert sneaky.status_code == 422, sneaky.text
    assert admin.get(f"{H}/{row['id']}").json()["visibility"] == "GROUPS"
    # 분명히 '전체 공개'라고 말하면 바뀐다.
    ok = admin.patch(f"{H}/{row['id']}", json={"expected_version": 1, "visibility": "ALL"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["visibility"] == "ALL"


def test_scope_check_warns_about_assignees_without_group_access(admin, users, db):
    """담당자가 그룹에 없으면 저장 전에 경고한다 — 막지는 않는다(일을 해야 하므로)."""
    gid = _group(db, users, "경고 확인 그룹")
    outsider = users["analyst"]["id"]
    warn = admin.post(f"{G}/scope-check", json={"visibility": "GROUPS", "group_ids": [gid],
                                                "user_ids": [outsider]})
    assert warn.status_code == 200, warn.text
    body = warn.json()
    assert body["public"] is False
    assert [x["user_id"] for x in body["outsiders"]] == [outsider]
    assert body["group_names"] == ["경고 확인 그룹"]
    # 남의 소속 그룹 **이름**은 돌려주지 않는다 — 이 응답으로 조 편성을 긁어 갈 수 있으면
    # 구성원 목록을 관리자에게만 보여 주는 통제가 무의미해진다.
    assert set(body["outsiders"][0]) == {"user_id", "display_name", "has_any_group"},         body["outsiders"][0]
    assert "관제" not in warn.text and "그룹" not in str(body["outsiders"])

    quiet = admin.post(f"{G}/scope-check", json={"group_ids": [], "user_ids": [outsider]})
    assert quiet.json() == {"visibility": "ALL", "group_names": [], "public": True,
                            "outsiders": []}


def test_legacy_conversion_needs_preview_phrase_and_backup(admin, other, users, db):
    """과거 자료 전체 공개 전환: 미리보기 → 확인 문구 → 백업 동의. 되돌릴 수 있다."""
    cid = _company_id(db)
    from app.models.group import HandoverGroup
    from app.services import group_service

    my_group = next(x["id"] for x in admin.get(f"{G}/mine").json())
    row = admin.post(H, json={"company_id": cid, "title": "과거 미분류 인계", "content": "본문",
                              "visibility": "GROUPS", "group_ids": [my_group]}).json()
    unclassified = group_service.ensure_unclassified(db)
    db.query(HandoverGroup).filter_by(handover_id=row["id"]).delete()
    db.add(HandoverGroup(handover_id=row["id"], group_id=unclassified.id))
    db.commit()
    # 외주 계정처럼 어느 그룹에도 들어 있지 않은 사람으로 확인한다.
    assert admin.put(f"/api/v1/users/{users['analyst']['id']}/groups",
                     json={"group_ids": []}).status_code == 200
    assert other.get(f"{H}/{row['id']}").status_code == 404, "전환 전에는 외주 계정이 못 본다"

    preview = admin.get(f"{G}/public-migration")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["eligible"] >= 1
    assert body["warnings"], "경고 없이 승인 화면을 보여 주면 안 된다"
    assert row["id"] in [x["id"] for x in body["items"]], "무엇이 공개되는지 목록으로 보여야 한다"

    assert admin.post(f"{G}/public-migration/apply", json={
        "confirm": "네", "backup_confirmed": True}).status_code == 422
    assert admin.post(f"{G}/public-migration/apply", json={
        "confirm": body["confirm_phrase"], "backup_confirmed": False}).status_code == 422
    assert other.get(f"{H}/{row['id']}").status_code == 404, "실패한 승인으로 공개되면 안 된다"

    done = admin.post(f"{G}/public-migration/apply", json={
        "confirm": body["confirm_phrase"], "backup_confirmed": True})
    assert done.status_code == 200, done.text
    assert other.get(f"{H}/{row['id']}").status_code == 200

    batches = admin.get(f"{G}/public-migration/batches").json()
    assert batches[0]["batch_id"] == done.json()["batch_id"]
    assert batches[0]["converted_by_name"]
    back = admin.post(f"{G}/public-migration/batches/{done.json()['batch_id']}/revert")
    assert back.status_code == 200, back.text
    assert back.json()["restored"] >= 1
    assert other.get(f"{H}/{row['id']}").status_code == 404, "되돌린 뒤 다시 가려져야 한다"


def test_conversion_never_touches_explicitly_grouped_material(admin, users, db):
    gid = _group(db, users, "건드리면 안 되는 그룹")
    cid = _company_id(db)
    kept = admin.post(H, json={"company_id": cid, "title": "명시 그룹 자료", "content": "본문",
                               "visibility": "GROUPS", "group_ids": [gid]}).json()
    preview = admin.get(f"{G}/public-migration").json()
    assert kept["id"] not in [x["id"] for x in preview["items"]]


# --------------------------------------------------------------------------- §2 감사 소음

def test_handover_view_audit_optional(admin, db):
    cid = _company_id(db)
    hid = admin.post(H, json={"company_id": cid, "title": "감사검사"}).json()["id"]
    assert admin.post(f"{H}/{hid}/view").status_code == 204
    assert not db.scalars(select(AuditLog).where(
        AuditLog.action == actions.HANDOVER_VIEW)).all()
    row = db.get(SystemSetting, "audit.track_handover_views")
    row.value = True
    db.commit()
    assert admin.post(f"{H}/{hid}/view").status_code == 204
    db.expire_all()
    assert len(db.scalars(select(AuditLog).where(
        AuditLog.action == actions.HANDOVER_VIEW)).all()) == 1


def test_audit_simplification_keeps_the_evidence_that_matters(admin, db):
    """소음을 줄여도 인증 실패 · 권한 · 내보내기 · 비밀번호 증적은 남는다."""
    from app.services import audit_service
    must_keep = {actions.LOGIN_FAILURE, actions.ACCOUNT_LOCKED, actions.ROLE_CHANGE,
                 actions.GROUP_MEMBER_CHANGE, actions.HANDOVER_SCOPE_CHANGE,
                 actions.EXCEL_EXPORT, actions.ATTACHMENT_UPLOAD, actions.ATTACHMENT_DELETE,
                 actions.CREDENTIAL_REVEAL, actions.CREDENTIAL_REVEAL_DENIED,
                 actions.CREDENTIAL_VAULT_BATCH_REVEAL, actions.SETTING_CHANGE,
                 actions.BACKUP, actions.RESTORE, actions.SCOPE_PUBLIC_MIGRATE}
    assert not (must_keep & audit_service.VIEW_ONLY_ACTIONS), "보존 대상을 숨기면 안 된다"
    assert audit_service.VIEW_ONLY_ACTIONS <= set(audit_service.ACTION_VIEWS["일반 열람"])
    assert must_keep <= set(audit_service.ACTION_VIEWS["중요 행위"]) | \
        set(audit_service.ACTION_VIEWS["인증 · 권한"]) | \
        set(audit_service.ACTION_VIEWS["데이터 변경"])


def test_failed_view_is_still_recorded(admin, other, users, db):
    """못 보게 막힌 흔적은 기본 설정에서도 남는다 — 조사의 출발점이다."""
    cid = _company_id(db)
    gid = _group(db, users, "열람 거부 확인 그룹")
    hid = admin.post(H, json={"company_id": cid, "title": "막힌 글", "content": "본문",
                              "visibility": "GROUPS", "group_ids": [gid]}).json()["id"]
    assert other.post(f"{H}/{hid}/view").status_code == 404
    db.expire_all()
    rows = db.scalars(select(AuditLog).where(AuditLog.action == actions.HANDOVER_VIEW)).all()
    assert [r.result for r in rows] == ["FAILURE"], "실패한 열람은 남아야 한다"


# --------------------------------------------------------------------------- §4 운영 지식

def test_knowledge_article_groups_and_file_download(admin, other, users, db):
    public = admin.post(K, json={"category": "운영 절차", "title": "야간 관제 SOP",
                                 "body": "확인→조치→인계"})
    assert public.status_code == 201, public.text
    pubid = public.json()["id"]
    assert other.get(f"{K}/{pubid}").status_code == 200
    files = {"file": ("sop.pdf", b"%PDF-1.4\nSOC runbook\n%%EOF", "application/pdf")}
    saved = admin.post("/api/v1/attachments",
                       data={"entity_type": "KNOWLEDGE", "entity_id": str(pubid)}, files=files)
    assert saved.status_code == 201, saved.text
    assert other.get(f"/api/v1/attachments/{saved.json()['id']}/download").status_code == 200

    gid = _group(db, users, "CERT 내부 운영 절차")
    private = admin.post(K, json={"category": "참고 자료", "title": "비공개 긴급 절차",
                                  "body": "권한 제한", "visibility": "GROUPS", "group_ids": [gid]})
    assert private.status_code == 201, private.text
    private_id = private.json()["id"]
    assert other.get(f"{K}/{private_id}").status_code == 404
    assert all(x["id"] != private_id for x in other.get(K).json())
    # 직접 URL · 첨부 번호를 알아도 접근할 수 없어야 한다.
    files2 = {"file": ("secret.pdf", b"%PDF-1.4\nPRIVATE\n%%EOF", "application/pdf")}
    second = admin.post("/api/v1/attachments",
                        data={"entity_type": "KNOWLEDGE", "entity_id": str(private_id)},
                        files=files2)
    assert second.status_code == 201, second.text
    assert other.get(f"/api/v1/attachments/{second.json()['id']}/download").status_code == 404
    # 개정 이력도 같은 판정을 지난다.
    assert other.get(f"{K}/{private_id}/revisions").status_code == 404


def test_knowledge_revisions_compare_and_restore(admin, db):
    created = admin.post(K, json={"category": "탐지·분석", "title": "C2 탐지 절차",
                                  "body": "1판 본문", "tags": ["c2", "탐지"]}).json()
    aid = created["id"]
    assert created["tags"] == ["c2", "탐지"]
    assert admin.patch(f"{K}/{aid}", json={"version_no": 1, "body": "2판 본문",
                                           "change_note": "임계치 수정"}).status_code == 200
    revs = admin.get(f"{K}/{aid}/revisions").json()
    assert [r["version_no"] for r in revs] == [2, 1], "최신 판이 위로"
    assert revs[0]["change_note"] == "임계치 수정"
    assert revs[0]["changed_by_name"]

    first = admin.get(f"{K}/{aid}/revisions/1").json()
    second = admin.get(f"{K}/{aid}/revisions/2").json()
    assert (first["body"], second["body"]) == ("1판 본문", "2판 본문"), "나란히 비교할 수 있다"

    back = admin.post(f"{K}/{aid}/revisions/1/restore")
    assert back.status_code == 200, back.text
    assert back.json()["body"] == "1판 본문"
    assert back.json()["version_no"] == 3, "복원은 새 판으로 올려 이력이 끊기지 않는다"
    assert len(admin.get(f"{K}/{aid}/revisions").json()) == 3


def test_knowledge_soft_delete_and_restore(admin, db):
    aid = admin.post(K, json={"category": "운영 절차", "title": "지웠다 되살릴 절차"}).json()["id"]
    assert admin.delete(f"{K}/{aid}").status_code == 204
    assert all(x["id"] != aid for x in admin.get(K).json()), "목록에서 사라진다"
    assert admin.get(f"{K}/{aid}").json()["is_deleted"] is True
    assert admin.post(f"{K}/{aid}/restore").status_code == 200
    assert any(x["id"] == aid for x in admin.get(K).json())


def test_knowledge_links_do_not_widen_handover_access(admin, other, users, db):
    """문서에 인계를 걸어도 그 인계를 볼 권한이 없는 사람에게는 보이지 않는다."""
    cid = _company_id(db)
    gid = _group(db, users, "연결 확인 내부 그룹")
    secret = admin.post(H, json={"company_id": cid, "title": "내부 전용 인계", "content": "본문",
                                 "visibility": "GROUPS", "group_ids": [gid]}).json()
    aid = admin.post(K, json={"category": "운영 절차", "title": "모두가 보는 절차"}).json()["id"]
    assert admin.post(f"{K}/{aid}/handovers",
                      json={"handover_id": secret["id"]}).status_code == 201

    assert [x["handover_id"] for x in admin.get(f"{K}/{aid}/handovers").json()] == [secret["id"]]
    assert other.get(f"{K}/{aid}").status_code == 200, "문서 자체는 전체 공개다"
    assert other.get(f"{K}/{aid}/handovers").json() == [], "볼 수 없는 인계는 목록에도 없다"
    # 볼 수 없는 인계는 걸 수도 없다.
    assert other.post(f"{K}/{aid}/handovers",
                      json={"handover_id": secret["id"]}).status_code == 404


def test_knowledge_template_and_keyword_suggestion(admin, db):
    body = admin.get(f"{K}/template").json()["body"]
    for section in ("목적 · 범위", "탐지 · 확인 기준", "분석 절차", "조치 방법",
                    "보고 · 전파 기준", "후속 확인", "관련 문서"):
        assert section in body, f"표준 양식에 '{section}' 이 없다"

    admin.post(K, json={"category": "탐지·분석", "title": "랜섬웨어 대응 절차",
                        "tags": ["랜섬웨어"]})
    admin.post(K, json={"category": "운영 절차", "title": "백업 점검 절차"})
    hits = admin.get(f"{K}/suggest?text=랜섬웨어 의심 트래픽 확인 요청").json()
    assert hits and hits[0]["title"] == "랜섬웨어 대응 절차"
    assert admin.get(f"{K}/suggest?text=관련 확인 조치").json() == [], "흔한 말로는 추천하지 않는다"


def test_knowledge_edit_rights_are_separate_from_read_rights(admin, other, db):
    aid = admin.post(K, json={"category": "운영 절차", "title": "읽기는 모두, 수정은 작성자"}).json()["id"]
    seen = other.get(f"{K}/{aid}").json()
    assert seen["can_edit"] is False
    assert other.patch(f"{K}/{aid}", json={"version_no": 1, "body": "남이 고침"}).status_code == 403
    assert other.delete(f"{K}/{aid}").status_code == 403


# --------------------------------------------------------------------------- §5 비밀번호 금고

def test_bulk_vault_unlock_restricts_personal_and_locks(admin, other, users, db):
    cid = _company_id(db)
    personal = admin.post(C, json={"company_id": cid, "device_name": "내 전용 계정",
                                   "scope": "PERSONAL", "username": "alice",
                                   "secret": "private-secret-2026!"})
    assert personal.status_code == 201, personal.text
    sid = personal.json()["id"]
    shared = other.post(C, json={"company_id": cid, "device_name": "공동 장비",
                                 "scope": "SHARED", "username": "socadmin",
                                 "secret": "shared-secret-2026!"})
    assert shared.status_code == 201, shared.text
    hid = shared.json()["id"]
    assert "private-secret-2026!" not in admin.get(C).text

    denied = other.post(f"{C}/vault/unlock", json={"password": "wrong"})
    assert denied.status_code == 403
    unlocked = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    assert unlocked.status_code == 200, unlocked.text
    token = unlocked.json()["token"]
    assert unlocked.json()["remaining_absolute_seconds"] <= 15 * 60, "연속 유지 상한 15분"
    headers = {"X-Vault-Token": token}
    exposed = other.get(f"{C}/vault/secrets?ids={hid}", headers=headers)
    assert exposed.status_code == 200, exposed.text
    assert exposed.json()[0]["secret"] == "shared-secret-2026!"
    assert other.get(f"{C}/vault/secrets?ids={sid}",
                     headers=headers).status_code == 404, "남의 개인 비밀번호는 일괄로도 안 보인다"
    assert other.post(f"{C}/vault/extend", headers=headers).status_code == 200
    assert other.post(f"{C}/vault/lock", headers=headers).status_code == 204
    assert other.get(f"{C}/vault/secrets?ids={hid}", headers=headers).status_code == 403
    db.expire_all()
    codes = {x for (x,) in db.execute(select(AuditLog.action))}
    assert {actions.CREDENTIAL_VAULT_UNLOCK, actions.CREDENTIAL_VAULT_BATCH_REVEAL,
            actions.CREDENTIAL_VAULT_DENIED, actions.CREDENTIAL_VAULT_EXTEND,
            actions.CREDENTIAL_VAULT_LOCK} <= codes


def test_vault_session_cannot_be_configured_beyond_fifteen_minutes(admin, db):
    """설정을 크게 바꿔도 코드가 15분에서 막는다."""
    from app.services import vault_session_service as vault
    for key, value in (("credential.unlock_minutes", 600),
                       ("credential.max_session_minutes", 600)):
        row = db.get(SystemSetting, key)
        row.value = value
        db.commit()
    ttl, hard = vault._minutes(db)
    assert (ttl, hard) == (vault.HARD_TTL_MINUTES, vault.HARD_MAX_MINUTES) == (10, 15)
    # 설정 API 로도 상한을 넘겨 저장할 수 없다.
    assert admin.patch("/api/v1/settings/credential.max_session_minutes",
                       json={"value": 60}).status_code == 422


def test_vault_session_dies_when_groups_or_role_change(admin, other, users, db):
    opened = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    assert opened.status_code == 200, opened.text
    headers = {"X-Vault-Token": opened.json()["token"]}
    assert other.get(f"{C}/vault/status", headers=headers).status_code == 200

    gid = _group(db, users, "권한 변경 확인 그룹")
    changed = admin.put(f"/api/v1/users/{users['analyst']['id']}/groups",
                        json={"group_ids": [gid], "default_group_id": gid})
    assert changed.status_code == 200, changed.text
    assert other.get(f"{C}/vault/status", headers=headers).status_code == 403, \
        "열람 범위가 바뀌면 열어 둔 금고는 닫혀야 한다"


def test_vault_lock_without_token_still_closes_the_session(other, db):
    opened = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    headers = {"X-Vault-Token": opened.json()["token"]}
    assert other.post(f"{C}/vault/lock").status_code == 204          # 토큰 없이 잠그기
    assert other.get(f"{C}/vault/status", headers=headers).status_code == 403


def test_vault_session_is_not_shared_between_users(admin, other, db):
    """같은 PC 에서 계정을 바꿔도 앞사람의 열람 세션을 물려받지 않는다."""
    opened = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    headers = {"X-Vault-Token": opened.json()["token"]}
    assert admin.get(f"{C}/vault/status", headers=headers).status_code == 403


def test_vault_batch_is_capped_and_rejects_duplicates(other, db):
    opened = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    headers = {"X-Vault-Token": opened.json()["token"]}
    many = "&".join(f"ids={i}" for i in range(1, 202))
    assert other.get(f"{C}/vault/secrets?{many}", headers=headers).status_code == 422
    assert other.get(f"{C}/vault/secrets?ids=1&ids=1", headers=headers).status_code == 422


def test_vault_responses_are_never_cached(other, db):
    opened = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    assert "no-store" in opened.headers.get("cache-control", "")
    headers = {"X-Vault-Token": opened.json()["token"]}
    got = other.get(f"{C}/vault/secrets?ids=0", headers=headers)
    assert "no-store" in got.headers.get("cache-control", "")


# --------------------------------------------------------------------------- §6 정기 점검

def test_recurring_inspection_completion_per_occurrence(admin, db):
    """'점검' 반복 일정의 회차별 완료. 어제 끝낸 것이 오늘 끝난 것으로 보이면 안 된다."""
    from datetime import date, timedelta

    today = date.today()
    made = admin.post("/api/v1/schedules", json={
        "title": "SIEM 수집 상태 점검", "event_type": "INSPECTION",
        "start_at": f"{today}T09:00:00+09:00", "end_at": f"{today}T09:30:00+09:00",
        "recurrence_rule": "FREQ=DAILY"})
    assert made.status_code == 201, made.text
    sid = made.json()["id"]

    rows = admin.get("/api/v1/schedules/inspections").json()
    mine = next(x for x in rows if x["schedule_id"] == sid)
    assert mine["is_done"] is False
    assert mine["recurrence_text"]

    done = admin.post(f"/api/v1/schedules/{sid}/completions",
                      json={"occurrence_date": str(today), "note": "정상"})
    assert done.status_code == 200, done.text
    assert done.json()["is_done"] is True
    assert done.json()["done_by_name"]

    after = next(x for x in admin.get("/api/v1/schedules/inspections").json()
                 if x["schedule_id"] == sid)
    assert after["is_done"] is True
    tomorrow = today + timedelta(days=1)
    nxt = admin.get(f"/api/v1/schedules/inspections?day={tomorrow}").json()
    assert next(x for x in nxt if x["schedule_id"] == sid)["is_done"] is False, \
        "오늘 끝냈다고 내일 회차가 끝난 것이 되면 안 된다"

    # 잘못 누른 완료는 되돌릴 수 있다.
    assert admin.delete(f"/api/v1/schedules/{sid}/completions/{today}").status_code == 204
    assert next(x for x in admin.get("/api/v1/schedules/inspections").json()
                if x["schedule_id"] == sid)["is_done"] is False


def test_non_inspection_schedules_cannot_be_completed(admin, db):
    from datetime import date

    today = date.today()
    made = admin.post("/api/v1/schedules", json={
        "title": "주간 회의", "event_type": "MEETING",
        "start_at": f"{today}T10:00:00+09:00", "end_at": f"{today}T11:00:00+09:00"})
    sid = made.json()["id"]
    bad = admin.post(f"/api/v1/schedules/{sid}/completions", json={"occurrence_date": str(today)})
    assert bad.status_code == 422, bad.text
    assert all(x["schedule_id"] != sid for x in admin.get("/api/v1/schedules/inspections").json())


def test_closing_check_counts_pending_inspections(admin, db):
    from datetime import date

    today = date.today()
    admin.post("/api/v1/schedules", json={
        "title": "근무 시작 장비 점검", "event_type": "INSPECTION",
        "start_at": f"{today}T09:00:00+09:00", "end_at": f"{today}T09:10:00+09:00",
        "recurrence_rule": "FREQ=DAILY"})
    rows = {r["key"]: r for r in admin.get("/api/v1/shift-handovers/closing-check").json()["rows"]}
    assert rows["inspections"]["count"] >= 1
    assert rows["inspections"]["url"].startswith("/schedules")


def test_conversion_handles_more_rows_than_one_sql_statement(admin, db, users, monkeypatch):
    """수만 건이 쌓인 DB 에서도 돌아야 한다 — IN (...) 을 나눠 보내는지 확인한다.

    한 문장에 다 넣으면 PostgreSQL 바인드 파라미터 상한(65535)에 걸려 전환 자체가
    실패한다. 여기서는 묶음 크기를 3 으로 줄여 나눠 보내는 길을 실제로 지나가게 한다.
    """
    from app.models.group import HandoverGroup
    from app.services import group_service

    monkeypatch.setattr(group_service, "_IN_CHUNK", 3)
    cid = _company_id(db)
    my_group = next(x["id"] for x in admin.get(f"{G}/mine").json())
    unclassified = group_service.ensure_unclassified(db)
    # API 로 먼저 다 만든다. 사이에 DB 세션이 쓰기 트랜잭션을 물고 있으면
    # SQLite 는 단일 writer 라 다음 POST 가 'database is locked' 로 막힌다.
    ids = [admin.post(H, json={"company_id": cid, "title": f"묶음 전환 {n}", "content": "본문",
                               "visibility": "GROUPS", "group_ids": [my_group]}).json()["id"]
           for n in range(7)]
    db.query(HandoverGroup).filter(HandoverGroup.handover_id.in_(ids)).delete(
        synchronize_session=False)
    for hid in ids:
        db.add(HandoverGroup(handover_id=hid, group_id=unclassified.id))
    db.commit()

    preview = admin.get(f"{G}/public-migration").json()
    assert preview["eligible"] == len(ids)
    done = admin.post(f"{G}/public-migration/apply", json={
        "confirm": preview["confirm_phrase"], "backup_confirmed": True})
    assert done.status_code == 200, done.text
    assert done.json()["converted"] == len(ids), "묶음 경계에서 빠진 건이 없어야 한다"
    assert all(admin.get(f"{H}/{i}").json()["visibility"] == "ALL" for i in ids)

    back = admin.post(f"{G}/public-migration/batches/{done.json()['batch_id']}/revert")
    assert back.status_code == 200 and back.json()["restored"] == len(ids), back.text
    assert all(admin.get(f"{H}/{i}").json()["visibility"] == "GROUPS" for i in ids)


def test_second_unlock_invalidates_the_first_tab(other, db):
    """같은 사람이 탭을 두 개 열고 각각 인증하면, 앞 탭의 열람은 끝난다.

    공용 콘솔에서 탭이 여러 개 열린 채 남는 일이 흔하다. 세션을 사람마다 하나만
    두면 '지금 잠그기' 한 번으로 그 사람의 열람이 확실히 끝난다.
    """
    first = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    assert first.status_code == 200, first.text
    h1 = {"X-Vault-Token": first.json()["token"]}
    assert other.get(f"{C}/vault/status", headers=h1).status_code == 200

    second = other.post(f"{C}/vault/unlock", json={"password": ANALYST_PW})
    assert second.status_code == 200, second.text
    h2 = {"X-Vault-Token": second.json()["token"]}
    assert other.get(f"{C}/vault/status", headers=h2).status_code == 200
    assert other.get(f"{C}/vault/status", headers=h1).status_code == 403, \
        "앞 탭의 토큰이 살아 있으면 '지금 잠그기'가 한 번으로 끝나지 않는다"

    assert other.post(f"{C}/vault/lock", headers=h2).status_code == 204
    assert other.get(f"{C}/vault/status", headers=h2).status_code == 403


def test_propagating_outside_the_scope_warns_before_sending(admin, users, db):
    """그룹 제한 글을 그 그룹 밖으로 전파하려 하면, 보내기 전에 알려 준다(§3).

    막지는 않는다 — 받는 사람이 그 일을 해야 하니까 전파하는 것이다. 다만
    '이 글은 A팀 전용인데 B팀도 읽게 된다'를 누르기 전에 알아야 한다.
    """
    cid = _company_id(db)
    inside = _group(db, users, "전파 경고 안쪽 그룹")
    outside = _group(db, users, "전파 경고 바깥 그룹")
    row = admin.post(H, json={"company_id": cid, "title": "그룹 제한 인계", "content": "본문",
                              "visibility": "GROUPS", "group_ids": [inside]}).json()

    same = admin.post(f"{H}/{row['id']}/propagate/preview",
                      json={"group_ids": [inside], "role": "FYI"})
    assert same.status_code == 200, same.text
    assert same.json()["outside_scope"] is None, "같은 그룹 안이면 경고할 것이 없다"

    out = admin.post(f"{H}/{row['id']}/propagate/preview",
                     json={"group_ids": [outside], "role": "FYI"})
    assert out.status_code == 200, out.text
    warn = out.json()["outside_scope"]
    assert warn is not None, "그룹 밖 전파인데 경고가 없다"
    assert warn["scope_groups"] == ["전파 경고 안쪽 그룹"]
    assert warn["outside_groups"] == ["전파 경고 바깥 그룹"]

    # 전체 공개 글에는 경고하지 않는다(넓힐 범위가 없다).
    public = admin.post(H, json={"company_id": cid, "title": "전체 공개", "content": "본문"}).json()
    plain = admin.post(f"{H}/{public['id']}/propagate/preview",
                       json={"group_ids": [outside], "role": "FYI"})
    assert plain.json()["outside_scope"] is None


def test_outside_scope_propagation_is_recorded_in_the_audit(admin, users, db):
    """그룹 밖 전파는 감사 기록만 보고도 알 수 있어야 한다.

    나중에 '이 글이 어떻게 저 팀에 갔지'를 조사할 때, 그때의 공개 그룹을 따로
    찾아 맞춰 보게 하면 안 된다.
    """
    cid = _company_id(db)
    inside = _group(db, users, "감사 기록 확인 안쪽")
    outside = _group(db, users, "감사 기록 확인 바깥")
    row = admin.post(H, json={"company_id": cid, "title": "감사 기록 확인 인계", "content": "본문",
                              "visibility": "GROUPS", "group_ids": [inside]}).json()
    sent = admin.post(f"{H}/{row['id']}/propagate",
                      json={"group_ids": [outside], "role": "FYI", "note": "확인용"})
    assert sent.status_code == 200, sent.text

    db.expire_all()
    log = db.scalars(select(AuditLog).where(
        AuditLog.action == actions.HANDOVER_PROPAGATE,
        AuditLog.resource_id == str(row["id"]))).all()
    assert log, "전파 기록이 없다"
    detail = log[-1].after_value or {}
    assert detail.get("outside_scope_groups") == ["감사 기록 확인 바깥"], detail
    assert detail.get("scope_groups") == ["감사 기록 확인 안쪽"], detail
    assert detail.get("visibility") == "GROUPS", detail
