"""인수인계 API 통합 테스트 — 실제 DB + 실제 라우터(§88, mock 금지)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.handover import ACK_ACKED, ACK_NONE, ACK_REACK
from app.models.reference import Company
from tests.conftest import ANALYST_PW, MANAGER_PW, ApiClient

BASE = "/api/v1/handovers"


@pytest.fixture
def company_id(db) -> int:
    """주의: 로그인 클라이언트에 의존하면 안 된다.

    client 픽스처는 테스트당 하나뿐이라, 여기서 admin_client 를 쓰면 ANALYST 로
    로그인한 테스트가 admin 으로 덮어써져 권한 테스트가 통과해 버린다.
    """
    cid = db.scalar(select(Company.id).order_by(Company.id))
    assert cid, "기준 데이터에 관계사가 있어야 한다"
    return cid


def _new(client, company_id: int, **over) -> dict:
    payload = {
        "company_id": company_id,
        "title": "방화벽 정책 변경 요청",
        "content": "10.0.0.1 → 10.0.0.2 허용 정책 추가",
        "status_code": "NEW",
        "priority_code": "NORMAL",
        **over,
    }
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- 생성

class TestCreate:
    def test_creates_with_version_one(self, admin_client, company_id):
        body = _new(admin_client, company_id)
        assert body["current_version_no"] == 1
        assert body["ack_state_cache"] == ACK_NONE
        assert body["registered_date"], "등록일이 비어 있으면 안 된다"

    def test_first_version_is_create_type(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        versions = admin_client.get(f"{BASE}/{hid}/versions").json()
        assert len(versions) == 1
        assert versions[0]["version_no"] == 1
        assert versions[0]["change_type"] == "CREATE"

    def test_v1_snapshot_holds_full_state(self, admin_client, company_id):
        hid = _new(admin_client, company_id, title="스냅샷 확인")["id"]
        v1 = admin_client.get(f"{BASE}/{hid}/versions/1").json()
        assert v1["before_data"] is None
        assert v1["after_data"]["title"] == "스냅샷 확인"
        assert "content" in v1["after_data"]

    def test_unknown_company_rejected(self, admin_client):
        resp = admin_client.post(BASE, json={"company_id": 999999, "title": "없는 관계사"})
        assert resp.status_code == 422

    def test_tags_are_stored_and_returned(self, admin_client, company_id):
        body = _new(admin_client, company_id, tags=["방화벽", "긴급"])
        assert body["tags"] == ["긴급", "방화벽"]  # 정렬되어 돌아온다


# --------------------------------------------------------------------------- 수정 / 버전

class TestUpdateAndVersion:
    def test_update_creates_new_version(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "title": "제목 수정"})
        assert resp.status_code == 200
        assert resp.json()["current_version_no"] == 2
        assert resp.json()["title"] == "제목 수정"

    def test_changed_fields_lists_only_what_changed(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}",
                           json={"expected_version": 1, "title": "새 제목",
                                 "content": "10.0.0.1 → 10.0.0.2 허용 정책 추가"})
        v2 = admin_client.get(f"{BASE}/{hid}/versions/2").json()
        assert v2["changed_fields"] == ["title"], "값이 같은 content 는 변경으로 치면 안 된다"

    def test_before_data_holds_only_changed_fields(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "새 제목"})
        v2 = admin_client.get(f"{BASE}/{hid}/versions/2").json()
        assert set(v2["before_data"]) == {"title"}
        assert v2["before_data"]["title"] == "방화벽 정책 변경 요청"
        # after_data 는 반대로 전체 스냅샷이어야 한다
        assert set(v2["after_data"]) > {"title", "content", "status_code"}

    def test_noop_update_creates_no_version(self, admin_client, company_id):
        created = _new(admin_client, company_id)
        hid = created["id"]
        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "title": created["title"]})
        assert resp.status_code == 200
        assert resp.json()["current_version_no"] == 1
        assert len(admin_client.get(f"{BASE}/{hid}/versions").json()) == 1

    def test_change_reason_is_kept(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "변경",
                                                 "change_reason": "고객사 요청"})
        v2 = admin_client.get(f"{BASE}/{hid}/versions/2").json()
        assert v2["change_reason"] == "고객사 요청"

    def test_empty_patch_rejected(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        resp = admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1})
        assert resp.status_code == 422

    def test_expected_version_is_mandatory(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        resp = admin_client.patch(f"{BASE}/{hid}", json={"title": "버전 없이 수정"})
        assert resp.status_code == 422, "expected_version 없이 수정이 통과하면 안 된다"


# --------------------------------------------------------------------------- 낙관적 잠금

class TestOptimisticLock:
    def test_stale_version_is_rejected(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "먼저 수정"})
        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "title": "뒤늦은 수정"})
        assert resp.status_code == 409
        assert resp.json()["error"] == "version_conflict"

    def test_conflict_reports_conflicting_fields(self, admin_client, company_id):
        """두 사람이 같은 필드를 동시에 고치면 어떤 필드가 겹쳤는지 알려줘야 한다."""
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "A 가 고친 제목"})

        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "title": "B 가 고친 제목"})
        detail = resp.json()["detail"]
        assert detail["current_version_no"] == 2
        assert detail["expected_version"] == 1
        assert detail["conflicting_fields"] == ["title"]
        assert detail["changed_since"] == ["title"]
        assert detail["current"]["title"] == "A 가 고친 제목", "현재 값을 함께 줘야 비교가 된다"

    def test_non_overlapping_edit_is_still_conflict_but_no_conflicting_field(
            self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "제목만 변경"})
        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "remark": "비고만 변경"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["conflicting_fields"] == []

    def test_two_users_second_writer_loses(self, admin_client, users, company_id):
        """§85 동시 수정 시나리오: 나중에 저장한 사람이 조용히 덮어쓰지 못한다."""
        hid = _new(admin_client, company_id, assignee_id=users["manager"]["id"])["id"]
        with ApiClient(app) as other:
            assert other.login("manager1", MANAGER_PW).status_code == 200
            assert other.patch(f"{BASE}/{hid}",
                               json={"expected_version": 1, "content": "관리자가 먼저 저장"}
                               ).status_code == 200
        resp = admin_client.patch(f"{BASE}/{hid}",
                                  json={"expected_version": 1, "content": "내가 나중에 저장"})
        assert resp.status_code == 409
        assert admin_client.get(f"{BASE}/{hid}").json()["content"] == "관리자가 먼저 저장"


# --------------------------------------------------------------------------- Diff / 복원

class TestDiffAndRestore:
    def test_diff_between_versions(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "변경된 제목"})
        body = admin_client.get(f"{BASE}/{hid}/versions/diff?from=1&to=2").json()
        assert body["changed_fields"] == ["title"]
        entry = body["fields"][0]
        assert entry["before"] == "방화벽 정책 변경 요청"
        assert entry["after"] == "변경된 제목"
        assert entry["ops"], "장문 필드에는 word-diff ops 가 있어야 한다"

    def test_restore_creates_new_version_not_rollback(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "v2 제목"})
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 2, "title": "v3 제목"})

        resp = admin_client.post(f"{BASE}/{hid}/versions/1/restore",
                                 json={"expected_version": 3, "change_reason": "오기입 되돌림"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["current_version_no"] == 4, "복원은 새 버전을 만든다"
        assert body["title"] == "방화벽 정책 변경 요청"

        v4 = admin_client.get(f"{BASE}/{hid}/versions/4").json()
        assert v4["change_type"] == "RESTORE"
        assert v4["restored_from_version"] == 1
        # 기존 버전은 그대로 남아 있어야 한다
        assert len(admin_client.get(f"{BASE}/{hid}/versions").json()) == 4

    def test_restore_requires_reason(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "v2"})
        resp = admin_client.post(f"{BASE}/{hid}/versions/1/restore",
                                 json={"expected_version": 2, "change_reason": ""})
        assert resp.status_code == 422

    def test_restore_to_identical_content_is_rejected(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        resp = admin_client.post(f"{BASE}/{hid}/versions/1/restore",
                                 json={"expected_version": 1, "change_reason": "의미 없는 복원"})
        assert resp.status_code == 409, "빈 버전을 만들지 않아야 한다"

    def test_restore_honours_optimistic_lock(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "v2"})
        resp = admin_client.post(f"{BASE}/{hid}/versions/1/restore",
                                 json={"expected_version": 1, "change_reason": "낡은 버전"})
        assert resp.status_code == 409

    def test_unknown_version_is_404(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        assert admin_client.get(f"{BASE}/{hid}/versions/99").status_code == 404


# --------------------------------------------------------------------------- 확인(Ack)

class TestAcknowledgement:
    def test_ack_records_version_at_click_time(self, admin_client, analyst_client, company_id):
        # admin 이 만들고 v2 까지 올린 뒤 analyst 가 확인 → v2 가 기록되어야 한다
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "v2 제목"})
        admin_client.logout()

        assert analyst_client.login("analyst1", ANALYST_PW).status_code == 200
        body = analyst_client.post(f"{BASE}/{hid}/acknowledge", json={"note": "확인함"}).json()
        assert body["state"] == ACK_ACKED
        assert body["acked_version_no"] == 2

    def test_reack_field_change_invalidates_ack(self, admin_client, company_id, users):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})

        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "내용이 바뀜"})
        acks = admin_client.get(f"{BASE}/{hid}/acknowledgements").json()
        mine = next(a for a in acks if a["user_id"] == users["analyst"]["id"])
        assert mine["state"] == ACK_REACK
        assert mine["stale_reason"] == ["title"]

    def test_non_reack_field_change_keeps_ack(self, admin_client, company_id, users):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})

        # remark 는 재확인 대상 필드가 아니다
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "remark": "메모 추가"})
        acks = admin_client.get(f"{BASE}/{hid}/acknowledgements").json()
        mine = next(a for a in acks if a["user_id"] == users["analyst"]["id"])
        assert mine["state"] == ACK_ACKED

    def test_ack_state_cache_follows_worst_state(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        assert admin_client.get(f"{BASE}/{hid}").json()["ack_state_cache"] == ACK_NONE
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})
        assert admin_client.get(f"{BASE}/{hid}").json()["ack_state_cache"] == ACK_ACKED
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "바뀜"})
        assert admin_client.get(f"{BASE}/{hid}").json()["ack_state_cache"] == ACK_REACK

    def test_pending_list_shows_reack_items(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})
            admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "바뀜"})
            pending = analyst.get("/api/v1/acknowledgements/pending").json()
        assert [p["state"] for p in pending] == [ACK_REACK]

    def test_ack_is_idempotent_per_user(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})
        assert len(admin_client.get(f"{BASE}/{hid}/acknowledgements").json()) == 1


# --------------------------------------------------------------------------- 권한 / 소유권

class TestPermissions:
    def test_analyst_can_edit_own(self, analyst_client, company_id):
        hid = _new(analyst_client, company_id)["id"]
        resp = analyst_client.patch(f"{BASE}/{hid}",
                                    json={"expected_version": 1, "title": "내 건 수정"})
        assert resp.status_code == 200

    def test_analyst_cannot_edit_others(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            resp = analyst.patch(f"{BASE}/{hid}",
                                 json={"expected_version": 1, "title": "남의 건 수정"})
        assert resp.status_code == 403

    def test_analyst_can_edit_when_assigned(self, admin_client, users, company_id):
        hid = _new(admin_client, company_id, assignee_id=users["analyst"]["id"])["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            resp = analyst.patch(f"{BASE}/{hid}",
                                 json={"expected_version": 1, "status_code": "IN_PROGRESS"})
        assert resp.status_code == 200

    def test_analyst_cannot_delete(self, analyst_client, company_id):
        hid = _new(analyst_client, company_id)["id"]
        resp = analyst_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "삭제 시도"})
        assert resp.status_code == 403

    def test_analyst_cannot_pin(self, analyst_client, company_id):
        hid = _new(analyst_client, company_id)["id"]
        assert analyst_client.post(f"{BASE}/{hid}/pin", json={"pinned": True}).status_code == 403


# --------------------------------------------------------------------------- 삭제 / 복구

class TestSoftDelete:
    def test_delete_requires_reason(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        resp = manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": ""})
        assert resp.status_code == 422

    def test_delete_keeps_row_and_adds_version(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        resp = manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "중복 등록"})
        assert resp.status_code == 200
        assert resp.json()["is_deleted"] is True
        assert resp.json()["delete_reason"] == "중복 등록"
        versions = manager_client.get(f"{BASE}/{hid}/versions").json()
        assert versions[0]["change_type"] == "DELETE"

    def test_deleted_is_hidden_from_analyst(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            assert analyst.get(f"{BASE}/{hid}").status_code == 404
            assert analyst.get(f"{BASE}?include_deleted=true").status_code == 422

    def test_manager_can_still_read_deleted(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        assert manager_client.get(f"{BASE}/{hid}").status_code == 200
        listed = manager_client.get(f"{BASE}?include_deleted=true").json()
        assert hid in [i["id"] for i in listed["items"]]

    def test_deleted_is_excluded_from_default_list(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        listed = manager_client.get(BASE).json()
        assert hid not in [i["id"] for i in listed["items"]]

    def test_deleted_cannot_be_updated(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        current = manager_client.get(f"{BASE}/{hid}").json()["current_version_no"]
        resp = manager_client.patch(f"{BASE}/{hid}",
                                    json={"expected_version": current, "title": "수정 시도"})
        assert resp.status_code == 409

    def test_only_admin_can_undelete(self, manager_client, company_id):
        hid = _new(manager_client, company_id)["id"]
        manager_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        assert manager_client.post(f"{BASE}/{hid}/undelete").status_code == 403

    def test_admin_undelete_restores_row(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.request("DELETE", f"{BASE}/{hid}", json={"reason": "정리"})
        resp = admin_client.post(f"{BASE}/{hid}/undelete")
        assert resp.status_code == 200
        assert resp.json()["is_deleted"] is False
        assert admin_client.get(f"{BASE}/{hid}/versions").json()[0]["change_type"] == "UNDELETE"


# --------------------------------------------------------------------------- 시점 재현 / Timeline

class TestAsOfAndTimeline:
    def test_as_of_reproduces_past_state(self, admin_client, company_id, db):
        from datetime import timedelta
        from urllib.parse import quote

        from app.models.handover import HandoverVersion

        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "나중 제목"})

        # Windows 시계 해상도(약 15ms) 때문에 v1/v2 의 changed_at 이 같은 값이 될 수 있다.
        # 시점 재현 질의 자체를 검증하려면 두 버전을 명시적으로 벌려 놓아야 한다.
        v1 = db.scalar(select(HandoverVersion).where(HandoverVersion.handover_id == hid,
                                                     HandoverVersion.version_no == 1))
        v1.changed_at = v1.changed_at - timedelta(days=1)
        db.commit()

        at = quote(v1.changed_at.isoformat())
        body = admin_client.get(f"{BASE}/{hid}?as_of={at}").json()
        assert body["version_no"] == 1
        assert body["data"]["title"] == "방화벽 정책 변경 요청"

    def test_as_of_with_tied_timestamps_returns_later_version(self, admin_client, company_id):
        """같은 시각에 두 버전이 있으면 '그 시각의 상태'는 나중 버전이다."""
        from urllib.parse import quote

        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "나중 제목"})
        v2_at = admin_client.get(f"{BASE}/{hid}/versions/2").json()["changed_at"]

        body = admin_client.get(f"{BASE}/{hid}?as_of={quote(v2_at)}").json()
        assert body["version_no"] == 2
        assert body["data"]["title"] == "나중 제목"

    def test_as_of_before_creation_is_404(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        assert admin_client.get(f"{BASE}/{hid}?as_of=2000-01-01T00:00:00%2B09:00"
                                ).status_code == 404

    def test_timeline_merges_versions_and_acks(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.patch(f"{BASE}/{hid}", json={"expected_version": 1, "title": "수정"})
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})

        events = admin_client.get(f"{BASE}/{hid}/timeline").json()
        kinds = [e["kind"] for e in events]
        assert kinds.count("VERSION") == 2
        assert "ACK" in kinds
        times = [e["at"] for e in events]
        assert times == sorted(times, reverse=True), "최신순이어야 한다"


# --------------------------------------------------------------------------- 목록 / 부가기능

class TestListAndExtras:
    def test_list_reports_total_and_total_all(self, admin_client, company_id):
        _new(admin_client, company_id, title="가나다")
        _new(admin_client, company_id, title="라마바")
        body = admin_client.get(f"{BASE}?q=가나다").json()
        assert body["total"] == 1
        assert body["total_all"] == 2

    def test_pinned_rows_come_first(self, admin_client, company_id):
        first = _new(admin_client, company_id, title="보통 건")["id"]
        second = _new(admin_client, company_id, title="고정할 건")["id"]
        admin_client.post(f"{BASE}/{second}/pin", json={"pinned": True})
        items = admin_client.get(BASE).json()["items"]
        assert items[0]["id"] == second
        assert first in [i["id"] for i in items]

    def test_pin_creates_a_version(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        admin_client.post(f"{BASE}/{hid}/pin", json={"pinned": True})
        v2 = admin_client.get(f"{BASE}/{hid}/versions/2").json()
        assert v2["changed_fields"] == ["is_pinned"]

    def test_star_is_personal(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        assert admin_client.post(f"{BASE}/{hid}/star").status_code == 204
        assert admin_client.get(f"{BASE}/{hid}").json()["is_starred"] is True
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            assert analyst.get(f"{BASE}/{hid}").json()["is_starred"] is False
        assert admin_client.request("DELETE", f"{BASE}/{hid}/star").status_code == 204
        assert admin_client.get(f"{BASE}/{hid}").json()["is_starred"] is False

    def test_my_ack_state_is_per_user(self, admin_client, company_id):
        hid = _new(admin_client, company_id)["id"]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"{BASE}/{hid}/acknowledge", json={})
            mine = analyst.get(BASE).json()["items"][0]
            assert mine["my_ack_state"] == ACK_ACKED
        others = admin_client.get(BASE).json()["items"][0]
        assert others["my_ack_state"] is None, "집계값과 내 확인상태를 혼동하면 안 된다"
        assert others["ack_state_cache"] == ACK_ACKED

    def test_filters_narrow_the_result(self, admin_client, company_id):
        _new(admin_client, company_id, status_code="NEW")
        _new(admin_client, company_id, status_code="IN_PROGRESS")
        body = admin_client.get(f"{BASE}?status_code=IN_PROGRESS").json()
        assert body["total"] == 1
        assert body["items"][0]["status"]["code"] == "IN_PROGRESS"

    def test_view_endpoint_writes_audit(self, admin_client, company_id, db):
        from sqlalchemy import select

        from app.models.common import AuditLog

        hid = _new(admin_client, company_id)["id"]
        assert admin_client.post(f"{BASE}/{hid}/view").status_code == 204
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "HANDOVER_VIEW")).all()
        assert [r.resource_id for r in rows] == [str(hid)]
