"""성능 측정 (NFR-02: 필터+정렬+페이징 P95 < 800ms, NFR-03: 목록 첫 페이지 P95 < 1.5s).

대량 데이터가 들어간 측정용 DB 로 앱을 띄운 뒤 실행한다.

    python -m tests.perf.bench_perf --base http://127.0.0.1:8096 --user admin --password ... --runs 12

각 시나리오를 예열 2회 + 본 측정 N회 실행하고 P50 · P95 · 최대값을 낸다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import date, timedelta

import httpx

TODAY = date.today()


def scenarios(company_id: int, user_id: int) -> list[dict]:
    month_ago = (TODAY - timedelta(days=30)).isoformat()
    return [
        {"name": "목록 첫 페이지(기본 정렬)", "method": "POST", "url": "/handovers/search",
         "json": {"page": 1, "size": 50}},
        {"name": "관계사 + 상태 필터", "method": "POST", "url": "/handovers/search",
         "json": {"filters": [{"field": "company_id", "op": "in", "value": [company_id]},
                              {"field": "status_code", "op": "in", "value": ["IN_PROGRESS", "NEW"]}],
                  "page": 1, "size": 50}},
        {"name": "최근 30일 + 수행일 정렬", "method": "POST", "url": "/handovers/search",
         "json": {"filters": [{"field": "registered_date", "op": "gte", "value": month_ago}],
                  "sort": [{"field": "work_date", "dir": "desc"}], "page": 1, "size": 50}},
        {"name": "담당자 + 미완료(Quick)", "method": "POST", "url": "/handovers/search",
         "json": {"filters": [{"field": "assignee_id", "op": "in", "value": [user_id]}],
                  "quick": ["OPEN"], "page": 1, "size": 50}},
        {"name": "전체 검색어(한글)", "method": "POST", "url": "/handovers/search",
         "json": {"q": "랜섬웨어", "page": 1, "size": 50}},
        {"name": "전체 검색어(IP 부분일치)", "method": "POST", "url": "/handovers/search",
         "json": {"q": "10.20.", "page": 1, "size": 50}},
        {"name": "검색어 + 필터 + 정렬", "method": "POST", "url": "/handovers/search",
         "json": {"q": "DDoS", "filters": [{"field": "priority_code", "op": "in", "value": ["HIGH", "URGENT"]}],
                  "sort": [{"field": "registered_date", "dir": "desc"}], "page": 1, "size": 50}},
        {"name": "깊은 페이지(100쪽)", "method": "POST", "url": "/handovers/search",
         "json": {"page": 100, "size": 50}},
        {"name": "컬럼 필터 값 목록(관계사)", "method": "POST", "url": "/handovers/facets",
         "json": {"field": "company_id", "limit": 50}},
        {"name": "통합검색(Ctrl+K)", "method": "POST", "url": "/search/global",
         "json": {"q": "웹셸", "limit": 8}},
        {"name": "상세 + 이력", "method": "GET", "url": "/handovers/{hid}"},
        {"name": "버전 목록", "method": "GET", "url": "/handovers/{hid}/versions"},
        {"name": "내 업무", "method": "GET", "url": "/my-work"},
        {"name": "교대 Cockpit", "method": "GET", "url": "/shift-handovers/cockpit"},
        {"name": "통계(1년)", "method": "GET",
         "url": f"/stats/summary?start={(TODAY - timedelta(days=365)).isoformat()}&end={TODAY.isoformat()}"},
        {"name": "감사 조회(최근 7일, 2쪽)", "method": "POST", "url": "/audit/search",
         "json": {"start": f"{(TODAY - timedelta(days=7)).isoformat()}T00:00:00+09:00",
                  "end": f"{(TODAY + timedelta(days=1)).isoformat()}T00:00:00+09:00", "page": 2, "size": 50}},
        {"name": "감사 조회(행위 필터)", "method": "POST", "url": "/audit/search",
         "json": {"start": f"{(TODAY - timedelta(days=30)).isoformat()}T00:00:00+09:00",
                  "end": f"{(TODAY + timedelta(days=1)).isoformat()}T00:00:00+09:00",
                  "actions": ["HANDOVER_UPDATE"], "page": 1, "size": 50}},
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8096")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--runs", type=int, default=12)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    api = a.base.rstrip("/") + "/api/v1"
    with httpx.Client(base_url=api, timeout=120) as c:
        r = c.post("/auth/login", json={"username": a.user, "password": a.password})
        r.raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")

        company_id = c.get("/companies").json()[0]["id"]
        first = c.post("/handovers/search", json={"page": 1, "size": 1}).json()
        total = first["total"]
        hid = first["items"][0]["id"]
        user_id = c.get("/auth/me").json()["id"]

        print(f"대상: {a.base}  인수인계 {total:,}건")
        rows = []
        for s in scenarios(company_id, user_id):
            url = s["url"].replace("{hid}", str(hid))
            times = []
            for i in range(a.runs + 2):
                t0 = time.perf_counter()
                if s["method"] == "GET":
                    resp = c.get(url)
                else:
                    resp = c.post(url, json=s["json"])
                dt = (time.perf_counter() - t0) * 1000
                if resp.status_code >= 400:
                    print(f"  ! {s['name']}: HTTP {resp.status_code} {resp.text[:200]}")
                    break
                if i >= 2:      # 앞 2회는 예열(캐시 · 연결)
                    times.append(dt)
            if not times:
                continue
            times.sort()
            p95 = times[max(0, int(len(times) * 0.95) - 1)]
            rows.append({"name": s["name"], "p50": round(statistics.median(times), 1),
                         "p95": round(p95, 1), "max": round(times[-1], 1), "runs": len(times)})
            print(f"  {s['name']:<28} p50 {rows[-1]['p50']:>7.1f}ms   p95 {rows[-1]['p95']:>7.1f}ms   최대 {rows[-1]['max']:>7.1f}ms")

    worst = max(rows, key=lambda r: r["p95"])
    print(f"\n가장 느린 것: {worst['name']} p95 {worst['p95']}ms")
    print(f"NFR-02 (필터+정렬+페이징 P95 < 800ms): {'통과' if worst['p95'] < 800 else '확인 필요'}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"total": total, "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
