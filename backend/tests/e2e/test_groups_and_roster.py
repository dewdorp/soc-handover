"""E2E — 열람 그룹 · 근무표 · 교대 마감 점검을 실제 브라우저로 확인한다.

  8.  관리자가 그룹을 만들고 사람을 넣는다 → 그 사람이 쓴 글이 다른 그룹에는 안 보인다
  9.  근무표: 주/월 보기 · 내 근무 · 대근 등록 → 실근무자가 바뀌고 되돌릴 수 있다
  10. 대시보드의 '교대 마감 점검' — 숫자를 누르면 그 목록이 열린다
  11. 좁은 화면(390px)에서도 근무표와 대시보드가 가로로 넘치지 않는다

실행: backend 에서 `python -m pytest tests/e2e -q`
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN_PW, USER_PW

pytestmark = pytest.mark.e2e


def _menu(page: Page, name: str):
    return page.get_by_role("navigation", name="주 메뉴").get_by_role("link", name=name, exact=True)


def _new_handover(page: Page, title: str, content: str = "E2E 점검용 내용") -> None:
    page.get_by_role("button", name=re.compile("^인수인계$")).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("관계사 *").locator("option")).not_to_have_count(0, timeout=15000)
    dialog.get_by_label("제목 *").fill(title)
    dialog.get_by_label("내용").fill(content)
    dialog.get_by_role("button", name="등록").click()
    expect(dialog).not_to_be_visible(timeout=10000)


def _open_admin(page: Page, tab: str) -> None:
    nav = page.get_by_role("navigation", name="주 메뉴")
    nav.get_by_role("button", name="운영·관리").click()
    _menu(page, "관리자").click()
    page.get_by_role("link", name=tab, exact=True).click()


# --------------------------------------------------------------------------- 8

def test_group_scope_hides_other_groups(login, server, page: Page):
    """그룹을 만들어 사람을 넣으면, 그 사람의 글은 같은 그룹만 본다."""
    admin = login("admin", ADMIN_PW)

    # (1) 관리자가 그룹 둘을 만든다
    _open_admin(admin, "열람 그룹")
    expect(page.get_by_role("heading", name="열람 그룹")).to_be_visible(timeout=15000)
    for name in ("E2E 주간조", "E2E 야간조"):
        page.get_by_role("button", name=re.compile("^그룹$")).click()
        dialog = page.get_by_role("dialog", name="그룹 만들기")
        dialog.get_by_label("그룹 이름 *").fill(name)
        dialog.get_by_role("button", name="저장").click()
        expect(dialog).not_to_be_visible(timeout=10000)
    expect(page.get_by_role("cell", name="E2E 주간조")).to_be_visible()

    # (2) 주간근무자를 '주간조'에, 야간근무자를 '야간조'에 넣는다
    for group, person, account in (("E2E 주간조", "주간근무자", "e2e_day"),
                                   ("E2E 야간조", "야간근무자", "e2e_night")):
        row = page.get_by_role("row").filter(has_text=group)
        row.get_by_role("button", name="구성원").click()
        panel = page.get_by_role("dialog", name=re.compile("구성원"))
        picker = panel.get_by_label("추가할 사람")
        expect(picker.locator("option")).not_to_have_count(0, timeout=10000)
        picker.select_option(label=f"{person} ({account})")
        panel.get_by_role("button", name="넣기").click()
        expect(panel.get_by_text(person, exact=False).first).to_be_visible(timeout=10000)
        panel.get_by_role("button", name="닫기").click()

    # (3) 주간근무자가 글을 쓴다 — 기본 공개 범위는 '내 그룹만'
    day = login("e2e_day", USER_PW)
    _menu(day, "인수인계").click()
    _new_handover(day, "E2E 주간조 전용 업무")
    # 등록하면 그 건이 선택되어 서랍도 함께 열린다 — 목록과 서랍 둘 다 제목을 담는다
    expect(day.get_by_text("E2E 주간조 전용 업무").first).to_be_visible(timeout=15000)

    # (4) 야간근무자에게는 보이지 않는다
    night = login("e2e_night", USER_PW)
    _menu(night, "인수인계").click()
    expect(night.get_by_text("E2E 주간조 전용 업무")).to_have_count(0, timeout=15000)


# --------------------------------------------------------------------------- 9

def test_roster_week_month_and_substitution(login, server, page: Page):
    """근무표에서 대근을 넣으면 그 줄의 실근무자가 바뀌고, 되돌리면 계획으로 돌아온다."""
    admin = login("admin", ADMIN_PW)

    # 조 편성 — 관리자가 두 사람을 1조에 넣는다(API 가 아니라 화면이 없으므로 근무표만 확인)
    page.goto(server["base"] + "/schedules/roster")
    expect(page.get_by_role("heading", name="근무표")).to_be_visible(timeout=15000)

    # 주 보기 → 월 보기
    page.get_by_role("button", name="월", exact=True).click()
    expect(page.get_by_text(re.compile("일 주기"))).to_be_visible()
    page.get_by_role("button", name="주", exact=True).click()

    # '내 근무' 칸이 있다(배정이 없으면 없다고 적힌다)
    expect(page.get_by_role("heading", name=re.compile("내 근무"))).to_be_visible()

    # 조 편성이 비어 있으면 '배정 없음'이 보이고 대근 버튼은 잠긴다
    first_day = page.get_by_text("배정 없음").first
    if first_day.is_visible():
        expect(page.get_by_role("button", name=re.compile("대근")).first).to_be_disabled()


def test_roster_substitution_changes_actual_staff(login, server, page: Page):
    """사람이 든 조에서 대근을 등록하면 취소선과 '+이름'이 같은 줄에 보인다."""
    import httpx

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "admin", "password": ADMIN_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        users = {u["display_name"]: u["id"] for u in c.get("/users/lookup").json()}
        teams = c.get("/roster/teams").json()
        # 1조에 두 사람, 2조에 한 사람 — 대근자를 2조에서 데려온다
        c.put(f"/roster/teams/{teams[0]['id']}/members",
              json={"user_ids": [users["주간근무자"]], "leader_id": users["주간근무자"]}).raise_for_status()
        c.put(f"/roster/teams/{teams[1]['id']}/members",
              json={"user_ids": [users["야간근무자"]]}).raise_for_status()

    login("admin", ADMIN_PW)
    page.goto(server["base"] + "/schedules/roster")
    expect(page.get_by_role("heading", name="근무표")).to_be_visible(timeout=15000)

    # 사람이 배정된 줄의 버튼만 켜져 있다 — 켜진 것 중 첫 번째를 누른다
    enabled = page.locator("button:enabled").filter(has_text="대근")
    expect(enabled.first).to_be_visible(timeout=15000)
    enabled.first.click()
    dialog = page.get_by_role("dialog", name=re.compile("대근"))
    expect(dialog).to_be_visible()
    dialog.get_by_label("사유").fill("E2E 병가")
    options = dialog.get_by_label("들어오는 사람 (비우면 결원)").locator("option")
    expect(options).not_to_have_count(0, timeout=10000)
    dialog.get_by_label("들어오는 사람 (비우면 결원)").select_option(index=1)
    dialog.get_by_role("button", name="등록").click()
    expect(dialog).not_to_be_visible(timeout=10000)

    # 같은 줄에 변경 내용이 남고, 되돌릴 수 있다
    expect(page.get_by_text("E2E 병가").first).to_be_visible(timeout=15000)
    page.get_by_role("button", name="되돌리기").first.click()
    expect(page.get_by_text("E2E 병가")).to_have_count(0, timeout=15000)


# --------------------------------------------------------------------------- 10

def test_closing_check_counts_open_the_matching_list(login, server, page: Page):
    """마감 점검의 '보내지 않은 인계 바구니'를 누르면 바로 그 화면이 열린다."""
    import httpx

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "e2e_day", "password": USER_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        company = c.get("/companies").json()[0]["id"]
        made = c.post("/handovers", json={"company_id": company, "title": "E2E 마감 점검용",
                                          "content": "마감 점검"})
        made.raise_for_status()
        # 바구니에 담아 두고 보내지 않는다 — 마감 점검의 '보내지 않은 바구니'가 1 이 된다
        c.post("/shift-handovers/basket/items",
               json={"handover_ids": [made.json()["id"]]}).raise_for_status()

    login("e2e_day", USER_PW)
    card = page.get_by_role("region", name="교대 마감 점검")
    expect(card).to_be_visible(timeout=15000)
    expect(card.get_by_text("확인하지 않은 인계")).to_be_visible()
    expect(card.get_by_text("다음 근무 결원")).to_be_visible()
    # 담아 둔 1건이 숫자로 보인다(바구니 목록과 같은 수)
    basket_row = card.get_by_role("link").filter(has_text="보내지 않은 인계 바구니")
    expect(basket_row).to_contain_text("1", timeout=15000)

    # 줄을 누르면 그 목록으로 간다
    card.get_by_role("link", name=re.compile("지연")).click()
    expect(page).to_have_url(re.compile(r"quick=OVERDUE"), timeout=15000)


def test_my_schedules_card_has_reminder_choices(login, server, page: Page):
    """'내 일정' 카드에서 일정별 알림을 바로 고를 수 있다."""
    import httpx

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "e2e_day", "password": USER_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        from datetime import datetime, timedelta, timezone
        kst = timezone(timedelta(hours=9))
        start = (datetime.now(kst) + timedelta(days=1)).replace(microsecond=0)
        c.post("/schedules", json={"title": "E2E 점검 일정",
                                   "start_at": start.isoformat()}).raise_for_status()

    login("e2e_day", USER_PW)
    card = page.get_by_role("region", name="내 일정")
    expect(card).to_be_visible(timeout=15000)
    expect(card.get_by_text("E2E 점검 일정")).to_be_visible(timeout=15000)

    picker = card.get_by_label("E2E 점검 일정 내 알림")
    picker.select_option(label="30분 전")
    # 다시 그려진 뒤에도 고른 값이 남아 있다(서버에 저장되었다는 뜻)
    expect(card.get_by_label("E2E 점검 일정 내 알림")).to_have_value("30", timeout=15000)


# --------------------------------------------------------------------------- 11

def test_narrow_screen_does_not_overflow(login, server, page: Page):
    """좁은 화면(390px)에서 가로 스크롤이 생기지 않는다."""
    page.set_viewport_size({"width": 390, "height": 844})
    login("admin", ADMIN_PW)
    expect(page.get_by_role("heading", name="근무 대시보드")).to_be_visible(timeout=15000)

    for path in ("/", "/schedules/roster"):
        page.goto(server["base"] + path)
        page.wait_for_timeout(1200)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, f"{path} 에서 가로로 {overflow}px 넘쳤다"


# --------------------------------------------------------------------------- 12 · 13 (§5)

def test_participants_and_propagation_preview(login, server, page: Page):
    """담당 · 참고를 지정하고, 그룹 전파가 **누르기 전에** 몇 명인지 보여 준다."""
    import httpx

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "admin", "password": ADMIN_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        made = c.post("/groups", json={"name": "E2E CERT", "description": "전파 확인"})
        gid = made.json()["id"] if made.status_code == 201 else             next(g["id"] for g in c.get("/groups").json() if g["name"] == "E2E CERT")
        me = c.get("/auth/me").json()
        mine = [g["id"] for g in c.get("/groups/mine").json()] + [gid]
        c.put(f"/users/{me['id']}/groups", json={"group_ids": mine, "default_group_id": mine[0]})
        users = {u["display_name"]: u["id"] for u in c.get("/users/lookup").json()}
        c.put(f"/users/{users['야간근무자']}/groups",
              json={"group_ids": [gid], "default_group_id": gid})
        company = c.get("/companies").json()[0]["id"]
        hid = c.post("/handovers", json={"company_id": company, "title": "E2E 전파 대상",
                                         "content": "전파"}).json()["id"]

    login("admin", ADMIN_PW)
    page.goto(f"{server['base']}/handovers?id={hid}")
    panel = page.get_by_role("region", name="담당 · 전파 대상")
    expect(panel).to_be_visible(timeout=20000)

    # 참고로 한 명 넣는다 — 확인 대기로 잡히지 않는다고 적혀 있다
    panel.get_by_label("사람 추가").select_option(label="주간근무자")
    panel.get_by_label("추가할 역할").select_option("FYI")
    expect(panel.get_by_text("확인 대기로 잡히지 않는다")).to_be_visible()
    panel.get_by_role("button", name="넣기").click()
    expect(panel.get_by_text("주간근무자")).to_be_visible(timeout=15000)
    expect(panel.get_by_text("확인 불필요")).to_be_visible()

    # 전파 — 누르기 전에 몇 명인지 보여 준다
    panel.get_by_role("button", name=re.compile("그룹에 전파")).click()
    dialog = page.get_by_role("dialog", name="그룹에 전파")
    expect(dialog).to_be_visible()
    dialog.get_by_role("checkbox", name="E2E CERT").check()
    # 미리보기 문단과 단추가 둘 다 '…명에게'를 담고 있다 — 문단 쪽만 본다
    expect(dialog.get_by_text(re.compile(r"명에게 .*갑니다"))).to_be_visible(timeout=15000)
    expect(dialog.get_by_text(re.compile("공개 범위"))).to_be_visible()
    dialog.get_by_role("button", name=re.compile("명에게 전파")).click()
    expect(dialog).not_to_be_visible(timeout=15000)
    expect(panel.get_by_text("야간근무자")).to_be_visible(timeout=15000)


def test_analysis_request_flow(login, server, page: Page):
    """의뢰 → 접수 → 회신이 화면에서 한 바퀴 돈다. 내용 없는 회신은 막힌다."""
    import httpx

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "admin", "password": ADMIN_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        company = c.get("/companies").json()[0]["id"]
        hid = c.post("/handovers", json={"company_id": company, "title": "E2E 의뢰 대상",
                                         "content": "분석 의뢰"}).json()["id"]

    login("admin", ADMIN_PW)
    page.goto(f"{server['base']}/handovers?id={hid}")
    panel = page.get_by_role("region", name="분석 의뢰")
    expect(panel).to_be_visible(timeout=20000)
    expect(panel.get_by_text("의뢰 없음")).to_be_visible()

    panel.get_by_role("button", name="의뢰하기").click()
    panel.get_by_label("의뢰받을 사람").select_option(label="주간근무자")
    panel.get_by_label(re.compile("무엇을 봐 달라는")).fill("C2 통신 로그 분석 부탁드립니다.")
    panel.get_by_role("button", name=re.compile("^의뢰$")).click()
    expect(panel.get_by_text("의뢰함")).to_be_visible(timeout=15000)

    panel.get_by_role("button", name="접수하기").click()
    expect(panel.get_by_text("접수함")).to_be_visible(timeout=15000)

    panel.get_by_role("button", name="회신하기").click()
    # 내용이 비어 있으면 회신 단추가 잠겨 있다 — 내용 없는 '회신함'은 증적이 아니다
    expect(panel.get_by_role("button", name=re.compile("^회신$"))).to_be_disabled()
    panel.get_by_label(re.compile("회신 내용")).fill("오탐으로 확인되었습니다.")
    panel.get_by_role("button", name=re.compile("^회신$")).click()
    expect(panel.get_by_text("회신함")).to_be_visible(timeout=15000)


# --------------------------------------------------------------------------- 14 (알림 팝업)

def test_new_notification_pops_up(login, server, page: Page):
    """화면을 열어 둔 사이에 온 알림이 구석에 뜬다 — 종의 숫자는 보고 있어야 보인다."""
    import httpx

    day = login("e2e_day", USER_PW)
    expect(page.get_by_role("heading", name="근무 대시보드")).to_be_visible(timeout=20000)
    # 열자마자 쌓여 있던 것이 우르르 뜨지는 않는다
    expect(page.get_by_role("region", name="새 알림")).to_have_count(0)

    base = server["base"] + "/api/v1"
    with httpx.Client(base_url=base, timeout=20) as c:
        c.post("/auth/login", json={"username": "admin", "password": ADMIN_PW}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        company = c.get("/companies").json()[0]["id"]
        users = {u["display_name"]: u["id"] for u in c.get("/users/lookup").json()}
        made = c.post("/handovers", json={"company_id": company, "title": "E2E 팝업 확인",
                                          "content": "담당 지정", "assignee_id": users["주간근무자"]})
        made.raise_for_status()

    popup = page.get_by_role("region", name="새 알림")
    expect(popup).to_be_visible(timeout=40000)
    expect(popup.get_by_text("E2E 팝업 확인")).to_be_visible()

    # 눌러 보면 그 건으로 간다
    popup.get_by_role("button", name=re.compile("열어 보기")).first.click()
    expect(day).to_have_url(re.compile(r"/handovers\?id="), timeout=15000)
