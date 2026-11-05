"""E2E 7종 (ARCHITECTURE §10 완료 판정) — 실제 브라우저(Edge)로 실제 서버를 쓴다.

  1. 로그인 · 대시보드
  2. 인수인계 등록 → 수정(새 버전) → 이전 버전으로 복원          (시나리오 B)
  3. 목록 검색 · Quick Filter                                    (시나리오 C)
  4. 할일 등록 → 완료 → 보드 확인                                (시나리오 D)
  5. 교대 인계: 바스켓 담기 → 보내기 → 받는 사람이 확인(Ack)      (시나리오 E)
  6. 그림 첨부: 올리기 → 목록의 미리보기 → 크게 보기
  7. 비밀번호 보관: 등록 → 목록에는 값이 안 보임 → 본인 확인 뒤 보기

실행: backend 에서 `python -m pytest tests/e2e -q` (Edge 필요). 느리므로 기본 테스트와 따로 돌린다.
"""
from __future__ import annotations

import re
import struct
import zlib

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN_PW, USER_PW

pytestmark = pytest.mark.e2e


def _menu(page: Page, name: str):
    """왼쪽 주 메뉴의 링크(같은 이름이 화면 안에도 있어 메뉴로 한정한다)."""
    return page.get_by_role("navigation", name="주 메뉴").get_by_role("link", name=name, exact=True)


def _new_handover(page: Page, title: str, content: str = "E2E 점검용 내용") -> None:
    page.get_by_role("button", name=re.compile("^인수인계$")).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    # 관계사 목록이 도착해야 기본값이 잡힌다 — 비어 있을 때 누르면 '존재하지 않는 관계사'로 거절당한다
    expect(dialog.get_by_label("관계사 *").locator("option")).not_to_have_count(0, timeout=15000)
    dialog.get_by_label("제목 *").fill(title)
    dialog.get_by_label("내용").fill(content)
    dialog.get_by_role("button", name="등록").click()
    expect(dialog).not_to_be_visible(timeout=10000)


def test_login_and_dashboard(login, server):
    page = login()
    expect(page.get_by_role("heading", name="근무 대시보드")).to_be_visible(timeout=15000)
    # 대시보드에는 근무에 쓰는 것만 둔다('시스템 상태 · 구현 현황'은 1.3.0 에서 뺐다).
    expect(page.get_by_text("구현 현황")).to_have_count(0)
    for card in ("교대 마감 점검", "내 일정", "인수 확인"):
        expect(page.get_by_text(card).first).to_be_visible(timeout=15000)
    # 왼쪽 메뉴가 권한대로 보인다(관리자)
    expect(_menu(page, "인수인계")).to_be_visible()
    page.get_by_role("navigation", name="주 메뉴").get_by_role("button", name="운영·관리").click()
    expect(_menu(page, "관리자")).to_be_visible()

    # 로그아웃하면 로그인 화면으로 돌아온다
    page.get_by_role("button", name="로그아웃").click()
    expect(page).to_have_url(re.compile("/login"), timeout=15000)


def test_handover_version_and_restore(login, server):
    page = login()
    _menu(page, "인수인계").click()
    _new_handover(page, "E2E 버전 시나리오", "최초 내용")

    page.get_by_text("E2E 버전 시나리오").first.click()
    drawer = page.get_by_role("complementary")
    expect(drawer.get_by_text("최초 내용")).to_be_visible()

    drawer.get_by_role("button", name="수정").click()
    drawer.locator("textarea").first.fill("고친 내용")   # 첫 번째가 내용, 두 번째가 비고
    drawer.get_by_role("button", name=re.compile("^저장")).click()
    expect(drawer.get_by_text("고친 내용")).to_be_visible(timeout=10000)

    drawer.get_by_role("tab", name="변경이력").click()
    expect(drawer.get_by_role("listitem").get_by_text("수정", exact=True)).to_be_visible()

    # v1 로 복원 → 새 버전(v3)이 생기고 내용이 처음으로 돌아온다
    drawer.get_by_role("button", name="복원").first.click()
    confirm = page.get_by_role("alertdialog")
    confirm.get_by_label(re.compile("복원 사유")).fill("E2E 되돌림")
    confirm.get_by_role("button", name="복원").click()
    expect(confirm).not_to_be_visible(timeout=10000)

    drawer.get_by_role("tab", name="상세").click()
    expect(drawer.get_by_text("최초 내용")).to_be_visible(timeout=10000)
    expect(drawer.get_by_text("v3", exact=True)).to_be_visible()


def test_search_and_quick_filter(login, server):
    page = login()
    _menu(page, "인수인계").click()
    _new_handover(page, "E2E 방화벽 정책 점검")
    _new_handover(page, "E2E 랜섬웨어 대응")

    search = page.get_by_placeholder(re.compile("^인수인계 검색"))
    search.fill("랜섬웨어")
    search.press("Enter")
    grid_row = lambda title: page.get_by_role("row").filter(has_text=title)
    expect(grid_row("E2E 랜섬웨어 대응")).to_be_visible(timeout=10000)
    expect(grid_row("E2E 방화벽 정책 점검")).to_have_count(0)
    expect(page.get_by_text(re.compile(r"현재 검색결과 1건"))).to_be_visible()

    search.fill("")
    search.press("Enter")
    page.get_by_role("button", name="미완료").click()
    expect(grid_row("E2E 방화벽 정책 점검")).to_be_visible(timeout=10000)


def test_task_create_and_complete(login, server):
    page = login()
    _menu(page, "내 업무").click()
    page.get_by_role("navigation", name="업무 메뉴").get_by_role("link", name="팀 할일").click()
    page.get_by_role("button", name="할일", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_label("제목 *").fill("E2E 야간 점검")
    dialog.get_by_role("button", name="만들기").click()
    expect(dialog).not_to_be_visible(timeout=10000)

    page.get_by_text("E2E 야간 점검").first.click()
    drawer = page.get_by_role("complementary")
    drawer.get_by_label("상태").select_option(label="완료")
    expect(drawer.get_by_label("상태")).to_have_value("DONE")
    expect(drawer.get_by_text(re.compile(r"완료 \d"))).to_be_visible(timeout=10000)   # 완료 시각

    page.goto(server["base"] + "/tasks/board")
    expect(page.get_by_text("E2E 야간 점검")).to_be_visible(timeout=10000)


def test_shift_transfer_and_ack(login, server, page: Page):
    # 주간 근무자: 인수인계 등록 → 바스켓 담기 → 야간 근무자에게 인계
    login("e2e_day", USER_PW)
    _menu(page, "인수인계").click()
    _new_handover(page, "E2E 야간 인계 건", "야간에 확인 필요")

    page.get_by_role("navigation", name="인수인계 메뉴").get_by_role("link", name="인계 준비").click()
    page.get_by_role("tab", name=re.compile("근무 중 신규")).click()   # Cockpit 영역 타일
    row = page.get_by_role("row").filter(has_text="E2E 야간 인계 건")
    row.get_by_role("checkbox").check()
    page.get_by_role("button", name=re.compile("인계 대상에 추가")).click()
    basket = page.get_by_role("complementary", name=re.compile("Basket"))
    expect(basket.get_by_text("E2E 야간 인계 건")).to_be_visible(timeout=10000)
    # 인수자 두 명 — 고른 사람은 칩으로 남고, 목록에서는 빠진다
    recipients = basket.get_by_label("받는 사람 추가")
    recipients.select_option(label="야간근무자")
    recipients.select_option(label="시스템 관리자")
    expect(basket.get_by_text(re.compile("2명 모두가 확인해야"))).to_be_visible(timeout=10000)

    basket.get_by_role("button", name=re.compile("다음 근무자에게 인계")).click()
    page.get_by_role("alertdialog").get_by_role("button", name="인계", exact=True).click()
    expect(page.get_by_text(re.compile("야간근무자 · 시스템 관리자 님에게 1건을 인계했습니다"))).to_be_visible(timeout=15000)

    # 야간 근무자: 인수 확인함에서 확인 — 같이 받은 사람이 보인다
    login("e2e_night", USER_PW)   # 로그인 고정구가 쿠키를 비우고 새로 로그인한다
    expect(page.get_by_text("E2E 야간 인계 건", exact=True).first).to_be_visible(timeout=15000)
    page.get_by_role("link", name="확인함 전체", exact=False).click()
    expect(page.get_by_text("E2E 야간 인계 건")).to_be_visible(timeout=15000)
    expect(page.get_by_text(re.compile("같이 받음: 시스템 관리자"))).to_be_visible(timeout=10000)
    page.get_by_role("button", name=re.compile("^확인$")).first.click()
    expect(page.get_by_text("확인할 인수인계가 없습니다.", exact=True)).to_be_visible(timeout=15000)


def _png_bytes() -> bytes:
    """진짜 PNG 한 장(8x8). 미리보기는 파일 내용으로 판단하므로 헤더가 진짜여야 한다."""
    width = height = 8
    raw = b"".join(b"\x00" + b"\x1e\x6e\xc8" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def test_image_attachment_preview(login, server, page: Page):
    """그림을 올리면 내려받지 않고 화면에서 본다(현장 요청)."""
    login()
    _menu(page, "인수인계").click()
    _new_handover(page, "E2E 화면 캡처 첨부")

    page.get_by_text("E2E 화면 캡처 첨부").first.click()
    drawer = page.get_by_role("complementary")
    drawer.get_by_role("tab", name=re.compile("^첨부")).click()
    drawer.get_by_label("첨부 파일").set_input_files({
        "name": "방화벽 화면.png", "mimeType": "image/png", "buffer": _png_bytes(),
    })

    # 목록에 미리보기(작은 그림)가 생긴다
    thumb = drawer.get_by_role("button", name=re.compile("크게 보기"))
    expect(thumb).to_be_visible(timeout=15000)

    # 눌러서 크게 보고, Esc 로 닫는다(뒤의 서랍은 열린 채로 남아야 한다)
    thumb.click()
    viewer = page.get_by_role("dialog", name=re.compile("그림 보기"))
    expect(viewer).to_be_visible(timeout=10000)
    expect(viewer.get_by_role("img", name="방화벽 화면.png")).to_be_visible()
    page.keyboard.press("Escape")
    expect(viewer).not_to_be_visible(timeout=10000)
    expect(drawer).to_be_visible()


def test_credential_vault(login, server, page: Page):
    """장비 비밀번호는 목록에 나오지 않고, 본인 확인을 거쳐야 한 번 보인다(현장 요청)."""
    secret = "Device#Pw2026!"
    login()
    _menu(page, "비밀번호").click()

    page.get_by_role("button", name=re.compile("^등록$")).click()
    dialog = page.get_by_role("dialog", name=re.compile("비밀번호 등록"))
    expect(dialog).to_be_visible(timeout=10000)
    dialog.get_by_label("장비명 *").fill("E2E 방화벽-01")
    dialog.get_by_label("접속 방법").fill("SSH 10.0.0.9:22")
    dialog.get_by_label("계정").fill("socadmin")
    dialog.get_by_label(re.compile("^비밀번호")).fill(secret)
    dialog.get_by_role("button", name="저장").click()
    expect(dialog).not_to_be_visible(timeout=10000)

    row = page.get_by_role("row").filter(has_text="E2E 방화벽-01")
    expect(row).to_be_visible(timeout=10000)
    assert secret not in page.content(), "목록 화면에 비밀번호가 실려 오면 안 된다"

    row.get_by_role("button", name=re.compile("보기")).click()
    viewer = page.get_by_role("dialog", name=re.compile("E2E 방화벽-01"))
    expect(viewer).to_be_visible(timeout=10000)

    viewer.get_by_label("본인 계정 비밀번호").fill("이건 틀린 비밀번호")
    viewer.get_by_role("button", name=re.compile("보기")).click()
    expect(viewer.get_by_text(re.compile("본인 비밀번호가 맞지 않습니다"))).to_be_visible(timeout=10000)

    viewer.get_by_label("본인 계정 비밀번호").fill(ADMIN_PW)
    viewer.get_by_role("button", name=re.compile("보기")).click()
    expect(viewer.get_by_label("비밀번호 값")).to_have_value(secret, timeout=10000)
    expect(viewer.get_by_text(re.compile("초 뒤에 저절로 닫힙니다"))).to_be_visible()

    viewer.get_by_role("button", name="닫기").click()
    expect(viewer).not_to_be_visible(timeout=10000)
