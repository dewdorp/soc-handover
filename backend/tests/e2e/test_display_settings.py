"""화면 설정 — 근무에 맞춘 밝기와 글자 크기. 실제 브라우저로 확인한다.

여기서 지키는 선
  · 고르면 바로 바뀌고, 새로고침 · 다시 로그인해도 그 사람 설정이 남는다.
  · 공용 PC 에서 다음 사람은 앞사람 설정이 아니라 기본값(근무에 맞춤 · 보통)으로 시작한다.
  · '근무에 맞춤'은 근무 설정의 야간 교대(기본 18:00~09:00)에 어둡고, 주간에 밝다.
  · 글자만 커진다 — 버튼 높이는 그대로다.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import USER_PW

pytestmark = pytest.mark.e2e

DARK_PAGE_BG = "rgb(12, 23, 27)"      # 야간 바탕(--surface-sunken)
LIGHT_PAGE_BG = "rgb(242, 246, 246)"  # 주간 바탕


def root(page: Page, name: str) -> str | None:
    return page.evaluate(f"document.documentElement.dataset.{name} ?? null")


def body_bg(page: Page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def body_font_px(page: Page) -> float:
    return float(page.evaluate("parseFloat(getComputedStyle(document.body).fontSize)"))


def open_menu(page: Page):
    page.get_by_role("button", name="화면 설정").click()
    dialog = page.get_by_role("dialog", name="화면 설정")
    expect(dialog).to_be_visible()
    return dialog


def test_choices_apply_at_once_and_stay_with_the_person(login, page: Page, server):
    page.clock.set_fixed_time("2026-11-24T13:00:00")      # 주간 — 기본(근무에 맞춤)은 밝다
    login()
    assert root(page, "theme") == "light" and body_bg(page) == LIGHT_PAGE_BG
    assert root(page, "textSize") == "normal"
    normal_font = body_font_px(page)
    button_height = page.get_by_role("button", name="화면 설정").bounding_box()["height"]

    dialog = open_menu(page)
    expect(dialog.get_by_text("지금은 주간 근무 시간이라 밝게 보입니다.")).to_be_visible()
    dialog.get_by_label("어둡게", exact=True).check()
    assert root(page, "theme") == "dark", "고르는 즉시 바뀐다"
    assert body_bg(page) == DARK_PAGE_BG
    # 글자 크기는 세 칸짜리 단추 — 사람이 누르는 글씨를 누른다(원형 칸은 화면에서 숨겨 두었다)
    dialog.get_by_text("크게", exact=True).click()
    expect(dialog.get_by_label("크게", exact=True)).to_be_checked()
    assert root(page, "textSize") == "large"
    assert body_font_px(page) > normal_font * 1.1, "글자가 커진다"
    assert page.get_by_role("button", name="화면 설정").bounding_box()["height"] == pytest.approx(button_height, abs=0.5), \
        "버튼 높이 · 배치는 그대로"

    # Esc 는 이 창만 닫는다
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()

    # 새로고침해도 — 첫 화면부터 어둡게(흰 화면이 번쩍이지 않게 그리기 전에 정한다)
    page.reload(wait_until="domcontentloaded")
    assert root(page, "theme") == "dark" and root(page, "textSize") == "large"

    # 같은 PC 의 다음 사람은 기본값으로 시작한다
    login("e2e_night", USER_PW)
    assert root(page, "theme") == "light", "앞사람의 '어둡게'를 물려받지 않는다(주간이므로 밝게)"
    assert root(page, "textSize") == "normal"

    # 원래 사람이 다시 들어오면 그 사람 설정이 돌아온다
    login()
    assert root(page, "theme") == "dark" and root(page, "textSize") == "large"


def test_follows_the_night_shift(login, page: Page, server):
    page.clock.set_fixed_time("2026-11-24T02:30:00")      # 야간 근무 한가운데
    login("e2e_day", USER_PW)
    assert root(page, "theme") == "dark", "근무에 맞춤(기본) — 야간 교대 시간에는 어둡다"
    assert body_bg(page) == DARK_PAGE_BG
    dialog = open_menu(page)
    expect(dialog.get_by_text("지금은 야간 근무 시간이라 어둡게 보입니다.")).to_be_visible()
    expect(dialog.get_by_text("야간 근무(18:00~09:00)에는 어둡게")).to_be_visible()
    page.keyboard.press("Escape")

    # 아침 교대(09:00) 뒤에는 밝게
    page.clock.set_fixed_time("2026-11-24T09:05:00")
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="화면 설정").wait_for()
    assert root(page, "theme") == "light"

    # '밝게'로 고정하면 야간에도 밝다
    dialog = open_menu(page)
    dialog.get_by_label("밝게", exact=True).check()
    page.keyboard.press("Escape")
    page.clock.set_fixed_time("2026-11-24T23:00:00")
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="화면 설정").wait_for()
    assert root(page, "theme") == "light"


def test_night_screen_keeps_status_colors_readable(login, page: Page, server):
    """야간 화면에서도 긴급 · 오류 표시는 바탕과 구분된다(대비 4.5:1 이상)."""
    page.clock.set_fixed_time("2026-11-24T03:00:00")
    login()
    page.goto(server["base"] + "/handovers")
    page.get_by_role("button", name="화면 설정").wait_for()
    ratio = page.evaluate("""() => {
      const parse = s => s.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number)
      const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 })
                                         .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0)
      const probe = document.createElement('span')
      probe.className = 'text-state-urgent bg-surface'
      probe.textContent = '긴급'
      document.body.appendChild(probe)
      const cs = getComputedStyle(probe)
      const a = lum(parse(cs.color)), b = lum(parse(cs.backgroundColor))
      probe.remove()
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    }""")
    assert ratio >= 4.5, f"야간 긴급 글자 대비 {ratio:.2f}"
