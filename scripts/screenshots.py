# -*- coding: utf-8 -*-
"""화면 갈무리 — 인수인계 전후나 릴리스 때 '무엇이 어떻게 보이는지'를 파일로 남긴다.

E2E 와 같은 도구(Playwright + 이 PC 의 Edge)를 쓴다. 사람이 브라우저를 열고 하나씩
누르는 대신, 같은 순서를 코드로 적어 두고 다시 돌릴 수 있게 한 것이다.

    python scripts/screenshots.py http://127.0.0.1:8099 admin <비밀번호> <저장폴더>

비밀번호는 인자로 받는다(소스에 두지 않는다). 시연용 인스턴스에만 쓴다.
좁은 화면(390px) 갈무리도 함께 만든다 — 현장 PC 가 아닌 노트북에서 여는 경우를 본다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

#: (파일 이름, 주소, 기다릴 글자, 설명)
SHOTS = [
    ("01-dashboard", "/", "교대 마감 점검", "대시보드 — 교대 마감 점검 · 인수 확인 · 내 업무 · 내 일정"),
    ("02-handovers", "/handovers", "인수인계 기록", "인수인계 목록 — 공개 그룹이 행마다 보인다"),
    ("03-shift-basket", "/shift", "다음 교대 인계", "인계 준비 — 다음 근무 실근무자로 인수자 채우기"),
    ("04-inbox", "/shift/inbox", "인수 확인", "인수 확인함 — 보고 있는 버전으로 확인"),
    ("05-roster-week", "/schedules/roster", "근무표", "근무표(주) — 계획 · 실제 · 결원"),
    ("06-admin-groups", "/admin/groups", "열람 그룹", "관리자 → 열람 그룹 — 구성원 · 미분류 이관"),
    ("06b-handover-detail", "/handovers?id=3", "담당 · 전파 대상",
     "업무 상세 — 대표/공동 담당 · 필수 인수자 · 참고, 분석 의뢰 흐름"),
    ("07-calendar", "/schedules", "일정", "팀 일정"),
    ("08-my-notes", "/my-work/notes", "메모", "내 메모 — 고른 글로 할 일 · 인계 초안"),
    ("09-stats", "/stats", "통계", "통계 — 내가 볼 수 있는 범위에서만 센다"),
    ("10-audit", "/audit", "감사", "감사로그 — 그룹 변경도 남는다"),
]

NARROW = [
    ("20-narrow-dashboard", "/", "교대 마감 점검", "좁은 화면(390px) — 대시보드"),
    ("21-narrow-roster", "/schedules/roster", "근무표", "좁은 화면(390px) — 근무표"),
]


def _login(page, base: str, username: str, password: str) -> None:
    page.goto(f"{base}/login", wait_until="domcontentloaded")
    page.get_by_label("계정").fill(username)
    page.get_by_label("비밀번호").fill(password)
    page.get_by_role("button", name="로그인").click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)


def _capture(page, base: str, out: Path, shots, suffix: str = "") -> list[str]:
    made = []
    for name, path, needle, label in shots:
        page.goto(base + path, wait_until="domcontentloaded")
        try:
            page.get_by_text(needle).first.wait_for(timeout=12000)
        except Exception:
            print(f"  ! {name}: '{needle}' 를 찾지 못했습니다 — 그대로 찍습니다")
        page.wait_for_timeout(1200)
        target = out / f"{name}{suffix}.png"
        page.screenshot(path=str(target), full_page=False)
        made.append(str(target))
        print(f"  {target.name}  {label}")
    return made


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    base, username, password, out_dir = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        try:
            wide = browser.new_context(viewport={"width": 1440, "height": 900},
                                       locale="ko-KR", device_scale_factor=1)
            page = wide.new_page()
            _login(page, base, username, password)
            print("넓은 화면 (1440x900)")
            _capture(page, base, out, SHOTS)
            wide.close()

            narrow = browser.new_context(viewport={"width": 390, "height": 844},
                                         locale="ko-KR", device_scale_factor=1)
            page = narrow.new_page()
            _login(page, base, username, password)
            print("좁은 화면 (390x844)")
            _capture(page, base, out, NARROW)
            narrow.close()
        finally:
            browser.close()

    print(f"완료 — {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
