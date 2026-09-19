"""할일 · 체크리스트 · 보드 · 내 업무 통합 테스트.

시나리오 D: 홍길동이 인수인계에서 할일을 바로 만들어(관계사·연결·내용 자동) 김철수에게
배정한다 → 김철수는 알림과 '내 업무 · 오늘'에서 보고, 체크리스트를 채우며 보드에서
진행중 → 대기 → 완료로 옮긴다 → 그 사이 관리자가 옛 버전으로 옮기면 409 → 상태가 바뀔
때마다 감사 기록이 남고, 인수인계 타임라인에 할일 추가·완료가 보인다. 인수인계 자체는
바뀌지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import KST, today, week_start
from app.main import app
from app.models.common import AuditLog
from app.models.reference import Company
from app.models.task import Task
from tests.conftest import ANALYST_PW, MANAGER_PW, ApiClient

T = "/api/v1/tasks"
H = "/api/v1/handovers"
W = "/api/v1/my-work"


def _client(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def people(users):
    hong = _client("analyst1", ANALYST_PW)
    kim = _client("analyst2", ANALYST_PW)
    mgr = _client("manager1", MANAGER_PW)
    yield {"hong": hong, "kim": kim, "mgr": mgr, "ids": users}
    for c in (hong, kim, mgr):
        c.__exit__(None, None, None)


@pytest.fixture
def cid(db) -> int:
    return db.scalar(select(Company.id).order_by(Company.id))


def _task(client, title="할일", **over) -> dict:
    resp = client.post(T, json={"title": title, **over})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _handover(client, cid, title="인수인계", **over) -> int:
    resp = client.post(H, json={"company_id": cid, "title": title, "content": title,
                                "status_code": "IN_PROGRESS", **over})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _board_ids(client, status: str, assignee: str = "all") -> list[int]:
    return [t["id"] for t in client.get(f"{T}/board", params={"assignee": assignee}).json()["columns"][status]]


# --------------------------------------------------------------------------- 시나리오 D

class TestScenarioD:
    def test_task_from_handover_to_done(self, people, cid, db):
        hong, kim, mgr = people["hong"], people["kim"], people["mgr"]
        kim_id = people["ids"]["analyst2"]["id"]
        body = "SSL VPN 해외 IP 접속 시도 5건. " * 40          # 500자 넘는 내용
        h = _handover(hong, cid, "SSL VPN 이상징후", content=body, priority_code="HIGH")

        # 인수인계에서 바로 만들기 — 비운 칸은 인수인계에서 채운다
        resp = hong.post(f"{H}/{h}/tasks", json={
            "assignee_id": kim_id, "due_date": today().isoformat(),
            "checklist": ["차단 목록 확인", "고객사 통보"]})
        assert resp.status_code == 201, resp.text
        task = resp.json()
        assert task["title"] == "SSL VPN 이상징후"
        assert task["company"]["id"] == cid and task["handover"]["id"] == h
        assert task["priority"]["code"] == "HIGH"
        assert task["description"].endswith("…") and len(task["description"]) == 501
        assert (task["creator"]["id"], task["assignee"]["id"]) == (people["ids"]["analyst"]["id"], kim_id)
        assert (task["status"], task["version_no"], task["checklist_total"]) == ("TODO", 1, 2)

        # 김철수: 배정 알림 · 내 업무 '오늘'
        notes = kim.get("/api/v1/notifications").json()
        assert [(n["type"], n["link_type"], n["link_id"]) for n in notes] == [("TASK_ASSIGNED", "TASK", task["id"])]
        work = kim.get(W, params={"bucket": "today"}).json()
        assert [(i["kind"], i["id"]) for i in work["items"]] == [("TASK", task["id"])]
        assert work["counts"]["today"] == 1 and work["counts"]["this_week"] == 1

        # 체크리스트 하나 끝내기 — 진행률
        first = kim.get(f"{T}/{task['id']}").json()["checklists"][0]
        done = kim.patch(f"/api/v1/checklists/{first['id']}", json={"is_done": True}).json()
        assert done["is_done"] and done["done_by"] == kim_id
        assert kim.get(f"{T}/{task['id']}").json()["checklist_done"] == 1

        # 보드: 진행중으로
        moved = kim.patch(f"{T}/{task['id']}/move", json={"expected_version": 1, "status": "IN_PROGRESS"})
        assert moved.status_code == 200 and moved.json()["version_no"] == 2

        # 관리자가 옛 화면(v1)에서 같은 카드를 옮기면 조용히 덮어쓰지 않는다
        stale = mgr.patch(f"{T}/{task['id']}/move", json={"expected_version": 1, "status": "TODO"})
        assert stale.status_code == 409
        assert stale.json()["detail"]["current_version_no"] == 2

        kim.patch(f"{T}/{task['id']}/move", json={"expected_version": 2, "status": "WAITING"})
        assert [i["id"] for i in kim.get(W, params={"bucket": "waiting"}).json()["items"]] == [task["id"]]

        finished = kim.patch(f"{T}/{task['id']}/move", json={"expected_version": 3, "status": "DONE"}).json()
        assert finished["completed_at"] is not None
        work = kim.get(W).json()
        assert work["counts"]["today"] == 0 and work["counts"]["done"] == 1

        # 상태가 바뀔 때마다 감사 기록
        logs = db.scalars(select(AuditLog).where(AuditLog.resource_type == "TASK",
                                                 AuditLog.resource_id == str(task["id"]))
                          .order_by(AuditLog.id)).all()
        assert [l.action for l in logs] == ["TASK_CREATE", "TASK_UPDATE", "TASK_UPDATE", "TASK_COMPLETE"]
        assert logs[1].after_value == {"status": "IN_PROGRESS", "via": "board"}

        # 인수인계: 할일 수 · 타임라인. 인수인계 자체는 그대로(v1)
        detail = hong.get(f"{H}/{h}").json()
        assert detail["task_count"] == 1 and detail["current_version_no"] == 1
        kinds = [e["kind"] for e in hong.get(f"{H}/{h}/timeline").json()]
        assert "TASK" in kinds and "TASK_DONE" in kinds


# --------------------------------------------------------------------------- 권한 · 검증

class TestPermissions:
    def test_only_creator_assignee_or_manager_can_edit(self, people):
        task = _task(people["hong"], "홍길동 할일")
        assert people["kim"].patch(f"{T}/{task['id']}", json={"expected_version": 1, "title": "x"}).status_code == 403
        assert people["mgr"].patch(f"{T}/{task['id']}", json={"expected_version": 1, "title": "관리자 수정"}).status_code == 200
        # 담당자로 지정되면 고칠 수 있다
        people["mgr"].patch(f"{T}/{task['id']}", json={"expected_version": 2,
                                                      "assignee_id": people["ids"]["analyst2"]["id"]})
        assert people["kim"].patch(f"{T}/{task['id']}", json={"expected_version": 3, "status": "IN_PROGRESS"}).status_code == 200

    def test_delete_is_for_creator_or_manager(self, people):
        task = _task(people["hong"], "지울 할일", assignee_id=people["ids"]["analyst2"]["id"])
        assert people["kim"].delete(f"{T}/{task['id']}").status_code == 403, "담당자라도 만든 사람이 아니면 못 지운다"
        assert people["hong"].delete(f"{T}/{task['id']}").status_code == 204
        assert people["hong"].get(f"{T}/{task['id']}").status_code == 404

    def test_checklist_follows_edit_permission(self, people):
        task = _task(people["hong"], "체크", checklist=["하나"])
        item = people["hong"].get(f"{T}/{task['id']}").json()["checklists"][0]
        assert people["kim"].patch(f"/api/v1/checklists/{item['id']}", json={"is_done": True}).status_code == 403
        assert people["kim"].post(f"{T}/{task['id']}/checklists", json={"title": "둘"}).status_code == 403

    def test_comments(self, people, db):
        task = _task(people["hong"], "댓글")
        c = people["kim"].post(f"{T}/{task['id']}/comments", json={"body": "로그 확인했습니다"})
        assert c.status_code == 201 and c.json()["author"] == "김철수"
        notes = people["hong"].get("/api/v1/notifications").json()
        assert notes[0]["type"] == "TASK_COMMENT", "만든 사람에게 알린다"
        assert people["hong"].delete(f"/api/v1/task-comments/{c.json()['id']}").status_code == 403
        assert people["kim"].delete(f"/api/v1/task-comments/{c.json()['id']}").status_code == 204
        assert people["hong"].get(f"{T}/{task['id']}").json()["comment_count"] == 0


class TestValidation:
    def test_due_before_start(self, people):
        resp = people["hong"].post(T, json={"title": "x", "start_date": "2026-09-20", "due_date": "2026-09-19"})
        assert resp.status_code == 422

    def test_patch_requires_expected_version(self, people):
        task = _task(people["hong"])
        assert people["hong"].patch(f"{T}/{task['id']}", json={"title": "y"}).status_code == 422

    def test_same_value_does_not_bump_version(self, people, db):
        task = _task(people["hong"], "같은 값")
        same = people["hong"].patch(f"{T}/{task['id']}", json={"expected_version": 1, "title": "같은 값"})
        assert same.json()["version_no"] == 1
        assert db.scalar(select(AuditLog).where(AuditLog.action == "TASK_UPDATE")) is None

    def test_inactive_assignee_rejected(self, people, db):
        from app.models.user import User
        kim = db.get(User, people["ids"]["analyst2"]["id"])
        kim.is_active = False
        db.commit()
        resp = people["hong"].post(T, json={"title": "x", "assignee_id": kim.id})
        assert resp.status_code == 422

    def test_leaving_done_clears_completed_at(self, people):
        task = _task(people["hong"], status="DONE")
        assert task["completed_at"] is not None
        back = people["hong"].patch(f"{T}/{task['id']}", json={"expected_version": 1, "status": "TODO"}).json()
        assert back["completed_at"] is None


# --------------------------------------------------------------------------- 보드

class TestBoard:
    def test_drop_after_a_card(self, people, db):
        hong = people["hong"]
        a, b, c = (_task(hong, n) for n in "ABC")
        assert _board_ids(hong, "TODO") == [a["id"], b["id"], c["id"]]
        hong.patch(f"{T}/{c['id']}/move", json={"expected_version": 1, "status": "TODO", "after_id": a["id"]})
        assert _board_ids(hong, "TODO") == [a["id"], c["id"], b["id"]]
        hong.patch(f"{T}/{b['id']}/move", json={"expected_version": 1, "status": "TODO"})
        assert _board_ids(hong, "TODO") == [b["id"], a["id"], c["id"]], "after_id 가 없으면 맨 위"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "TASK_UPDATE")) is None, \
            "같은 칸 안의 순서 바꾸기는 감사 기록이 아니다"

    def test_filtered_board_keeps_global_order(self, people):
        """내 것만 보이는 보드에서 옮겨도 남의 카드 사이 순서가 어긋나지 않는다."""
        hong, kim = people["hong"], people["kim"]
        mine1 = _task(hong, "내1")
        other = _task(kim, "남")
        mine2 = _task(hong, "내2")
        assert _board_ids(hong, "TODO", "me") == [mine1["id"], mine2["id"]]
        hong.patch(f"{T}/{mine2['id']}/move", json={"expected_version": 1, "status": "TODO", "after_id": other["id"]})
        assert _board_ids(hong, "TODO") == [mine1["id"], other["id"], mine2["id"]]

    def test_done_column_shows_recent_only(self, people, db):
        hong = people["hong"]
        old, new = _task(hong, "옛날", status="DONE"), _task(hong, "최근", status="DONE")
        db.get(Task, old["id"]).completed_at = datetime.now(KST) - timedelta(days=30)
        db.commit()
        assert _board_ids(hong, "DONE") == [new["id"]]

    def test_canceled_is_not_a_board_column(self, people):
        task = _task(people["hong"])
        resp = people["hong"].patch(f"{T}/{task['id']}/move", json={"expected_version": 1, "status": "CANCELED"})
        assert resp.status_code == 422


# --------------------------------------------------------------------------- 내 업무

class TestMyWork:
    def test_buckets(self, people, cid):
        hong, kim = people["hong"], people["kim"]
        hong_id = people["ids"]["analyst"]["id"]
        t0 = today()
        week_end = week_start(t0) + timedelta(days=6)
        overdue = _task(hong, "지난 마감", due_date=(t0 - timedelta(days=1)).isoformat())
        due_today = _task(hong, "오늘 마감", due_date=t0.isoformat())
        later = _task(hong, "다음주", due_date=(week_end + timedelta(days=1)).isoformat())
        no_date = _task(hong, "날짜 없음")
        waiting = _task(hong, "대기", status="WAITING")
        _task(kim, "남의 할일", due_date=t0.isoformat())
        h = _handover(kim, cid, "내 담당 인수인계", assignee_id=hong_id, work_date=t0.isoformat())
        # 김철수가 교대 인계로 넘기면 확인필요
        other = _handover(kim, cid, "넘겨받은 건")
        kim.post("/api/v1/shift-handovers/basket/items", json={"handover_ids": [other]})
        kim.post("/api/v1/shift-handovers/basket/send", json={"to_user_id": hong_id})

        def ids(bucket, source="all"):
            return {(i["kind"], i["id"]) for i in hong.get(W, params={"bucket": bucket, "source": source}).json()["items"]}

        assert ids("overdue") == {("TASK", overdue["id"])}
        assert ids("today") == {("TASK", due_today["id"]), ("HANDOVER", h)}
        assert ("TASK", due_today["id"]) in ids("this_week")
        assert ids("upcoming") == {("TASK", later["id"])}
        assert ids("waiting") == {("TASK", waiting["id"])}
        assert ids("need_ack") == {("ACK", other)}
        assert ("TASK", no_date["id"]) in ids("all")
        assert all(k == "TASK" for k, _ in ids("all", "task"))

        body = hong.get(W).json()
        assert body["items"][0]["id"] == overdue["id"], "지연이 맨 위"
        assert body["counts"]["need_ack"] == 1 and body["counts"]["overdue"] == 1
        assert hong.get(W, params={"source": "task"}).json()["counts"]["need_ack"] == 0, \
            "건수는 고른 출처 기준"


# --------------------------------------------------------------------------- 목록 · 검색

class TestSearch:
    def test_filters(self, people):
        hong = people["hong"]
        _task(hong, "방화벽 정책", description="A보안 요청 3건")
        _task(hong, "완료된 일", status="DONE")
        _task(people["kim"], "김철수 일")

        def titles(**body):
            return {t["title"] for t in hong.post(f"{T}/search", json=body).json()["items"]}

        assert titles(q="요청") == {"방화벽 정책"}, "설명도 찾는다"
        assert "완료된 일" not in titles()
        assert "완료된 일" in titles(include_closed=True)
        assert titles(assignee="me") == {"방화벽 정책"}
        assert titles(q="%") == set(), "LIKE 와일드카드는 글자 그대로"

    def test_global_search_includes_tasks(self, people, cid):
        _task(people["hong"], "DDoS 임계치 조정")
        _handover(people["hong"], cid, "DDoS 탐지")
        body = people["hong"].post("/api/v1/search/global", json={"q": "DDoS"}).json()
        assert {h["type"] for h in body["hits"]} == {"handover", "task"}
        assert (body["totals"]["handover"], body["totals"]["task"]) == (1, 1)
