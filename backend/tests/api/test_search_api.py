"""검색 API 통합 테스트 — 실제 DB 질의가 나가는 경로를 검증한다."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.handover import ACK_ACKED, ACK_NONE
from app.models.reference import Company
from tests.conftest import ANALYST_PW, ApiClient

SEARCH = "/api/v1/handovers/search"
FACETS = "/api/v1/handovers/facets"


@pytest.fixture
def companies(db) -> list[int]:
    """기본 관계사 + 추가 2개."""
    existing = list(db.scalars(select(Company.id).order_by(Company.id)))
    for name in ("A보안", "B금융"):
        db.add(Company(name=name))
    db.commit()
    return existing + list(db.scalars(
        select(Company.id).where(Company.name.in_(("A보안", "B금융"))).order_by(Company.id)))


def _mk(client, company_id, **over) -> dict:
    payload = {"company_id": company_id, "title": "기본 제목", "content": "기본 내용",
               "status_code": "NEW", "priority_code": "NORMAL", **over}
    resp = client.post("/api/v1/handovers", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def dataset(admin_client, companies, users):
    """검색 테스트용 고정 데이터."""
    c0, c1, c2 = companies[0], companies[1], companies[2]
    rows = [
        _mk(admin_client, c1, title="DDoS 공격 탐지", content="외부에서 SYN Flood 유입",
            status_code="IN_PROGRESS", priority_code="URGENT", is_important=True,
            registered_date="2026-08-01", work_date="2026-08-02", tags=["DDoS", "네트워크"]),
        _mk(admin_client, c1, title="방화벽 정책 변경", content="10.0.0.1 허용 요청",
            status_code="DONE", priority_code="NORMAL",
            registered_date="2026-08-15", work_date="2026-08-16", tags=["방화벽"]),
        _mk(admin_client, c2, title="EDR 경고 조사", content="랜섬웨어 의심 프로세스",
            status_code="WAITING", priority_code="HIGH",
            assignee_id=users["analyst"]["id"],
            registered_date="2026-09-01", work_date="2026-09-02", tags=["EDR"]),
        _mk(admin_client, c0, title="정기 점검", content="월간 보안 점검 수행",
            status_code="CANCELED", priority_code="LOW",
            registered_date="2026-09-10"),
    ]
    return {"ids": [r["id"] for r in rows], "companies": companies}


def _titles(body) -> set[str]:
    return {i["title"] for i in body["items"]}


# --------------------------------------------------------------------------- 필터

class TestColumnFilters:
    def test_in_filter_on_company(self, admin_client, dataset):
        c1 = dataset["companies"][1]
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "company_id", "op": "in", "value": [c1]}]}).json()
        assert body["total"] == 2
        assert _titles(body) == {"DDoS 공격 탐지", "방화벽 정책 변경"}

    def test_contains_is_case_and_substring_based(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "content", "op": "contains", "value": "랜섬웨어"}]}).json()
        assert _titles(body) == {"EDR 경고 조사"}

    def test_not_contains_includes_null_rows(self, admin_client, dataset):
        """비고가 비어 있는 행이 '미포함' 결과에서 빠지면 사용자는 행을 잃어버린다."""
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "remark", "op": "not_contains", "value": "없는말"}]}).json()
        assert body["total"] == 4

    def test_starts_with(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "title", "op": "starts_with", "value": "방화벽"}]}).json()
        assert _titles(body) == {"방화벽 정책 변경"}

    def test_between_on_date(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "registered_date", "op": "between",
                         "value": ["2026-08-01", "2026-08-31"]}]}).json()
        assert body["total"] == 2

    def test_is_null_on_assignee(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "assignee_id", "op": "is_null"}]}).json()
        assert body["total"] == 3

    def test_filters_are_anded(self, admin_client, dataset):
        c1 = dataset["companies"][1]
        body = admin_client.post(SEARCH, json={"filters": [
            {"field": "company_id", "op": "in", "value": [c1]},
            {"field": "status_code", "op": "in", "value": ["DONE"]},
        ]}).json()
        assert _titles(body) == {"방화벽 정책 변경"}

    def test_tags_any_of(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "tags", "op": "any_of_tags",
                         "value": ["EDR", "방화벽"]}]}).json()
        assert _titles(body) == {"EDR 경고 조사", "방화벽 정책 변경"}

    def test_status_category_covers_multiple_codes(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "status_category", "op": "in", "value": ["CLOSED"]}]}).json()
        assert _titles(body) == {"방화벽 정책 변경", "정기 점검"}

    def test_percent_in_search_term_is_literal(self, admin_client, companies):
        """'100%' 검색이 와일드카드로 해석되면 전혀 다른 결과가 나온다."""
        _mk(admin_client, companies[0], title="CPU 100% 도달")
        _mk(admin_client, companies[0], title="CPU 정상")
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "title", "op": "contains", "value": "100%"}]}).json()
        assert _titles(body) == {"CPU 100% 도달"}


class TestRejections:
    def test_unknown_field_is_422(self, admin_client):
        resp = admin_client.post(SEARCH, json={
            "filters": [{"field": "password_hash", "op": "eq", "value": "x"}]})
        assert resp.status_code == 422
        assert resp.json()["error"] == "validation_error"

    def test_sql_injection_attempt_is_422(self, admin_client):
        resp = admin_client.post(SEARCH, json={
            "filters": [{"field": "title) OR 1=1 --", "op": "eq", "value": "x"}]})
        assert resp.status_code == 422

    def test_injection_in_value_is_treated_as_text(self, admin_client, dataset):
        """값은 바인드 파라미터라 그냥 문자열이다. 테이블이 남아 있어야 한다."""
        body = admin_client.post(SEARCH, json={
            "filters": [{"field": "title", "op": "contains",
                         "value": "'; DROP TABLE handovers; --"}]}).json()
        assert body["total"] == 0
        assert admin_client.post(SEARCH, json={}).json()["total"] == 4

    def test_non_sortable_field_is_422(self, admin_client):
        resp = admin_client.post(SEARCH, json={"sort": [{"field": "content", "dir": "asc"}]})
        assert resp.status_code == 422

    def test_extra_body_key_is_rejected(self, admin_client):
        resp = admin_client.post(SEARCH, json={"raw_sql": "SELECT 1"})
        assert resp.status_code == 422


# --------------------------------------------------------------------------- Quick

class TestQuickFilters:
    def test_open_excludes_closed(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"quick": ["OPEN"]}).json()
        assert _titles(body) == {"DDoS 공격 탐지", "EDR 경고 조사"}

    def test_important(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"quick": ["IMPORTANT"]}).json()
        assert _titles(body) == {"DDoS 공격 탐지"}

    def test_mine_binds_to_caller(self, admin_client, dataset):
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            body = analyst.post(SEARCH, json={"quick": ["MINE"]}).json()
        assert _titles(body) == {"EDR 경고 조사"}

    def test_overdue_needs_past_work_date_and_open_status(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"quick": ["OVERDUE"]}).json()
        assert _titles(body) == {"DDoS 공격 탐지", "EDR 경고 조사"}

    def test_need_ack_is_per_user(self, admin_client, dataset):
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            assert analyst.post(SEARCH, json={"quick": ["NEED_ACK"]}).json()["total"] == 0

    def test_quick_filters_combine_with_and(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"quick": ["OPEN", "IMPORTANT"]}).json()
        assert _titles(body) == {"DDoS 공격 탐지"}

    def test_quick_and_filters_combine(self, admin_client, dataset):
        c2 = dataset["companies"][2]
        body = admin_client.post(SEARCH, json={
            "quick": ["OPEN"],
            "filters": [{"field": "company_id", "op": "in", "value": [c2]}]}).json()
        assert _titles(body) == {"EDR 경고 조사"}


# --------------------------------------------------------------------------- Global / 정렬

class TestGlobalSearchAndSort:
    def test_q_searches_across_fields(self, admin_client, dataset):
        assert _titles(admin_client.post(SEARCH, json={"q": "SYN Flood"}).json()) \
            == {"DDoS 공격 탐지"}

    def test_q_matches_company_name_through_search_text(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"q": "B금융"}).json()
        assert _titles(body) == {"EDR 경고 조사"}

    def test_q_and_filters_work_together(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "q": "점검", "filters": [{"field": "status_code", "op": "in",
                                   "value": ["CANCELED"]}]}).json()
        assert _titles(body) == {"정기 점검"}

    def test_sort_desc(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "sort": [{"field": "registered_date", "dir": "desc"}]}).json()
        assert body["items"][0]["title"] == "정기 점검"

    def test_sort_asc(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={
            "sort": [{"field": "registered_date", "dir": "asc"}]}).json()
        assert body["items"][0]["title"] == "DDoS 공격 탐지"

    def test_pinned_rows_lead_regardless_of_sort(self, admin_client, dataset):
        last = dataset["ids"][0]
        admin_client.post(f"/api/v1/handovers/{last}/pin", json={"pinned": True})
        body = admin_client.post(SEARCH, json={
            "sort": [{"field": "registered_date", "dir": "desc"}]}).json()
        assert body["items"][0]["id"] == last

    def test_global_palette_returns_snippets(self, admin_client, dataset):
        body = admin_client.post("/api/v1/search/global",
                                 json={"q": "랜섬웨어", "limit": 5}).json()
        assert body["totals"]["handover"] == 1
        assert body["hits"][0]["title"] == "EDR 경고 조사"
        assert "랜섬웨어" in body["hits"][0]["snippet"]
        assert "내용" in body["hits"][0]["matched"]

    def test_global_tells_which_field_matched(self, admin_client, dataset):
        """본문에 없는 이름으로 걸린 건은 어느 칸인지 알려준다."""
        hid = dataset["ids"][0]
        resp = admin_client.patch(f"/api/v1/handovers/{hid}", json={"expected_version": 1,
                                                                   "checker_name_raw": "박확인"})
        assert resp.status_code == 200, resp.text
        body = admin_client.post("/api/v1/search/global", json={"q": "박확인", "scope": ["handover"]}).json()
        assert body["totals"] == {"handover": 1}
        assert body["hits"][0]["matched"] == ["확인자"]
        assert body["hits"][0]["snippet"] == "확인자: 박확인"

    def test_global_scope_limits_types(self, admin_client, dataset):
        body = admin_client.post("/api/v1/search/global", json={"q": "EDR", "scope": ["task"]}).json()
        assert set(body["totals"]) == {"task"} and all(h["type"] == "task" for h in body["hits"])

    def test_paging_reports_totals(self, admin_client, dataset):
        body = admin_client.post(SEARCH, json={"size": 2, "page": 1}).json()
        assert len(body["items"]) == 2
        assert body["total"] == 4
        assert body["total_all"] == 4
        assert body["has_next"] is True
        assert admin_client.post(SEARCH, json={"size": 2, "page": 2}).json()["has_next"] is False


# --------------------------------------------------------------------------- Facet

class TestFacets:
    def test_facet_counts_by_company(self, admin_client, dataset):
        rows = admin_client.post(FACETS, json={"field": "company_id"}).json()
        counts = {r["label"]: r["count"] for r in rows}
        assert counts["A보안"] == 2
        assert counts["B금융"] == 1

    def test_facet_reflects_other_filters(self, admin_client, dataset):
        """Excel 자동필터처럼, 다른 필터가 걸리면 건수도 줄어야 한다."""
        c1 = dataset["companies"][1]
        rows = admin_client.post(FACETS, json={
            "field": "status_code",
            "filters": [{"field": "company_id", "op": "in", "value": [c1]}]}).json()
        assert {r["value"] for r in rows} == {"IN_PROGRESS", "DONE"}

    def test_facet_ignores_its_own_filter(self, admin_client, dataset):
        """상태 필터를 걸어도 상태 값 목록은 전부 보여야 선택을 바꿀 수 있다."""
        rows = admin_client.post(FACETS, json={
            "field": "status_code",
            "filters": [{"field": "status_code", "op": "in", "value": ["DONE"]}]}).json()
        assert len(rows) == 4

    def test_facet_labels_resolve_names(self, admin_client, dataset):
        rows = admin_client.post(FACETS, json={"field": "status_code"}).json()
        labels = {r["value"]: r["label"] for r in rows}
        assert labels["IN_PROGRESS"] == "진행중"

    def test_facet_search_narrows_values(self, admin_client, dataset):
        rows = admin_client.post(FACETS, json={"field": "company_id",
                                               "facet_q": "금융"}).json()
        assert [r["label"] for r in rows] == ["B금융"]

    def test_tag_facet(self, admin_client, dataset):
        rows = admin_client.post(FACETS, json={"field": "tags"}).json()
        assert {r["value"] for r in rows} == {"DDoS", "네트워크", "방화벽", "EDR"}

    def test_my_ack_facet_is_per_user(self, admin_client, dataset):
        hid = dataset["ids"][0]
        with ApiClient(app) as analyst:
            analyst.login("analyst1", ANALYST_PW)
            analyst.post(f"/api/v1/handovers/{hid}/acknowledge", json={})
            rows = analyst.post(FACETS, json={"field": "my_ack_state"}).json()
        counts = {r["value"]: r["count"] for r in rows}
        assert counts[ACK_ACKED] == 1
        assert counts[ACK_NONE] == 3

    def test_non_facetable_field_is_422(self, admin_client, dataset):
        assert admin_client.post(FACETS, json={"field": "content"}).status_code == 422


# --------------------------------------------------------------------------- 레지스트리 / GET 동치

class TestCapabilitiesAndGetParity:
    def test_fields_endpoint_describes_the_registry(self, admin_client):
        body = admin_client.get("/api/v1/search/fields").json()
        names = {f["name"] for f in body["fields"]}
        assert {"company_id", "status_code", "tags", "my_ack_state"} <= names
        assert {q["token"] for q in body["quick_filters"]} >= {"TODAY", "OPEN", "OVERDUE"}
        assert "any_of_tags" in body["operators"]

    def test_get_list_and_post_search_agree(self, admin_client, dataset):
        c1 = dataset["companies"][1]
        via_get = admin_client.get(f"/api/v1/handovers?company_id={c1}").json()
        via_post = admin_client.post(SEARCH, json={
            "filters": [{"field": "company_id", "op": "eq", "value": c1}]}).json()
        assert via_get["total"] == via_post["total"]
        assert _titles(via_get) == _titles(via_post)

    def test_get_list_accepts_quick_tokens(self, admin_client, dataset):
        body = admin_client.get("/api/v1/handovers?quick=OPEN,IMPORTANT").json()
        assert _titles(body) == {"DDoS 공격 탐지"}

    def test_alias_endpoint_matches(self, admin_client, dataset):
        a = admin_client.post(SEARCH, json={"quick": ["OPEN"]}).json()
        b = admin_client.post("/api/v1/search/handovers", json={"quick": ["OPEN"]}).json()
        assert _titles(a) == _titles(b)
