# -*- coding: utf-8 -*-
"""설치된 서버에서 '경계가 실제로 서 있는가'를 확인한다 — 설치 PC 에서 돌릴 수 있는 점검.

개발 PC 의 시험은 SQLite 로 돈다. 설치 PC 는 PostgreSQL 이다. 행 잠금 · 상관 서브쿼리 ·
집계처럼 DB 마다 다르게 도는 자리가 있어, 설치한 뒤 한 번은 **그 PC 에서** 확인해야 한다.

    python scripts/verify_install.py http://localhost:8080 admin <비밀번호>

읽기만 한다(아무것도 만들거나 지우지 않는다). 시연 데이터가 들어 있는 상태에서 돌린다.
"""
from __future__ import annotations

import sys

import httpx

OK, NG = "  [OK]", "  [NG]"


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    base, username, password = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
    bad = 0

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal bad
        print(f"{OK if passed else NG} {label}{(' — ' + detail) if detail else ''}")
        bad += 0 if passed else 1

    with httpx.Client(base_url=f"{base}/api/v1", timeout=30, follow_redirects=True) as c:
        health = c.get("/health").json()
        print(f"서버 {health['version']} · DB {health['database']}")
        c.post("/auth/login", json={"username": username, "password": password}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")

        # --- 1. 열람 그룹이 실제로 나뉘어 있는가
        groups = c.get("/groups").json()
        check("열람 그룹이 있다", len(groups) >= 2, f"{len(groups)}개")
        named = [g for g in groups if g["code"] != "UNCLASSIFIED"]
        check("'미분류' 말고 실제 그룹이 있다", bool(named),
              " · ".join(g["name"] for g in named) or "없음 — 관리자 화면에서 만드십시오")
        left = c.get("/groups/unclassified/summary").json()
        check("미분류로 남은 자료가 없다", left["total"] == 0,
              f"{left['total']}건 남음 — 관리자 → 열람 그룹에서 옮기십시오")

        # --- 2. 다른 그룹의 업무가 섞이지 않는가 (사람마다 보이는 수가 다른가)
        users = {u["display_name"]: u["id"] for u in c.get("/users/lookup?limit=100").json()}
        mine = c.get("/handovers", params={"size": 1}).json()
        check("목록이 열린다", "total_all" in mine, f"내가 보는 전체 {mine.get('total_all')}건")

        # --- 3. 근무표가 맞물리는가
        cov = c.get("/roster/coverage", params={"days": 32}).json()
        check("32일 동안 매일 주간 1조 · 야간 1조", cov["ok"],
              "" if cov["ok"] else f"어긋난 날 {len(cov['problems'])}일 — 조의 주기 위치를 확인하십시오")
        teams = c.get("/roster/teams").json()
        sizes = {t["code"]: len(t["members"]) for t in teams}
        check("네 조에 사람이 들어 있다", all(v > 0 for v in sizes.values()),
              " · ".join(f"{k}{v}명" for k, v in sizes.items()))

        # --- 4. 다음 근무의 실제 근무자가 나오는가
        nxt = c.get("/roster/next-shift").json()
        check("다음 근무 인수자가 정해진다", bool(nxt["user_ids"]),
              f"{nxt['work_date']} {nxt['shift_label']} · " + (", ".join(nxt["names"]) or "없음"))
        if nxt["is_short"]:
            print(f"       (결원 {nxt['short_by']}명 — 근무표를 확인하십시오)")

        # --- 5. 마감 점검이 목록과 같은 수를 세는가
        closing = c.get("/shift-handovers/closing-check").json()
        rows = {r["key"]: r["count"] for r in closing["rows"]}
        basket = len(c.get("/shift-handovers/basket").json()["items"])
        check("마감 점검의 '바구니' 수 = 실제 바구니", rows.get("basket") == basket,
              f"점검 {rows.get('basket')} vs 바구니 {basket}")
        inbox = len(c.get("/shift-handovers/inbox").json())
        check("마감 점검의 '확인하지 않은 인계' 수 = 확인함", rows.get("unacked") == inbox,
              f"점검 {rows.get('unacked')} vs 확인함 {inbox}")

        # --- 6. 색인에 넣지 말아야 할 것이 사례에 섞이지 않는가
        cases = c.get("/rag/cases", params={"limit": 200}).json()
        blob = str(cases)
        creds = c.get("/credentials").json()
        leaked = [x["device_name"] for x in (creds.get("items") or creds if isinstance(creds, dict) else creds)
                  if isinstance(x, dict) and x.get("device_name") and x["device_name"] in blob]
        check("RAG 사례에 비밀번호 보관 항목이 없다", not leaked, ", ".join(leaked))
        notes = c.get("/me/notes").json()
        leaked_notes = [n["title"] for n in notes if n["body"] and n["body"][:20] in blob]
        check("RAG 사례에 개인 메모가 없다", not leaked_notes, ", ".join(leaked_notes))

        # --- 7. 못 보는 건은 404 로 답하는가(관리자 계정으로는 확인할 수 없으므로 안내만)
        print("  [--] 다른 그룹 차단은 그 그룹에 속하지 않은 계정으로 로그인해 확인하십시오")

    print()
    if bad:
        print(f"확인 실패 {bad}건 — 위 [NG] 줄을 보십시오.")
        return 1
    print("모두 통과.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
