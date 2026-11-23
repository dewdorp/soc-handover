"""서식 있는 본문 — 실제 브라우저로 끝까지 해 본다(요청 시나리오 A · B · C · D).

탐지 결과표 작성 → 로그 입력 → 화면 캡처 붙여넣기 → 저장 → 다음 교대자 확인 →
댓글로 후속 분석. 스크린샷 붙여넣기는 PNG 파일을 담은 실제 paste 이벤트로,
Excel 표 붙여넣기는 클립보드 HTML 로 흉내 낸다(사람이 Ctrl+V 할 때 브라우저가 받는 것과 같다).
"""
from __future__ import annotations

import base64
import io
import re
import struct
import zlib
from contextlib import contextmanager

import httpx
import pytest
from openpyxl import load_workbook
from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import ADMIN_PW, USER_PW

pytestmark = pytest.mark.e2e

EDITOR = "인수인계 내용"
HTTP_LOG = 'GET /board.php?id=1%27--<script>alert("xss")</script> HTTP/1.1\nHost: www.example.co.kr'
EXCEL_TABLE = ("<html><body><table><tr><td>항목</td><td>탐지 내용</td><td>분석 결과</td><td>조치</td></tr>"
               "<tr><td>WAF</td><td>SQL Injection 의심</td><td>반복 요청 확인</td><td>차단</td></tr>"
               "<tr><td>IPS</td><td>동일 IP 반복 탐지</td><td>관련성 분석</td><td>모니터링</td></tr>"
               "<tr><td>NDR</td><td>추가 통신 탐지</td><td>내부 영향 확인</td><td>조사 중</td></tr>"
               "</table></body></html>")


def png(width: int = 160, height: int = 90, rgb: bytes = b"\x20\x60\xc0") -> bytes:
    raw = b"".join(b"\x00" + rgb * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@contextmanager
def api(server, username="admin", password=ADMIN_PW):
    c = httpx.Client(base_url=f"{server['base']}/api/v1", timeout=30)
    try:
        c.post("/auth/login", json={"username": username, "password": password}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        yield c
    finally:
        c.close()


def paste_image(editor: Locator, data: bytes, name: str = "image.png", *, focus: bool = True) -> None:
    """Ctrl+V 로 스크린샷을 붙여 넣을 때 브라우저가 편집기에 주는 이벤트를 그대로 만든다."""
    if focus:
        editor.click()
    editor.evaluate("""(el, [b64, name]) => {
        const bin = atob(b64); const bytes = new Uint8Array(bin.length)
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
        const dt = new DataTransfer()
        dt.items.add(new File([bytes], name, { type: 'image/png' }))
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
    }""", [base64.b64encode(data).decode(), name])


def paste_html(editor: Locator, html: str) -> None:
    """Excel 에서 표를 복사해 붙여 넣을 때 — 클립보드에 HTML 과 그림이 함께 온다."""
    editor.click()
    editor.evaluate("""(el, [html, b64]) => {
        const dt = new DataTransfer()
        dt.setData('text/html', html)
        dt.setData('text/plain', '항목\\t탐지 내용')
        const bin = atob(b64); const bytes = new Uint8Array(bin.length)
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
        dt.items.add(new File([bytes], 'excel.png', { type: 'image/png' }))   // Excel 이 함께 넣는 그림
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
    }""", [html, base64.b64encode(png(8, 8)).decode()])


def find_handover(server, title: str) -> dict:
    with api(server) as c:
        found = c.post("/search/handovers", json={"q": title, "page": 1, "size": 5}).json()["items"]
        assert found, f"'{title}' 를 찾지 못했다"
        return c.get(f"/handovers/{found[0]['id']}").json()


def open_drawer(page: Page, server, handover_id: int) -> Locator:
    page.goto(f"{server['base']}/handovers?id={handover_id}")
    drawer = page.get_by_role("complementary", name="인수인계 상세")
    expect(drawer).to_be_visible(timeout=20000)
    return drawer


def image_loaded(img: Locator) -> bool:
    return img.evaluate("el => el.complete && el.naturalWidth > 0")


# --------------------------------------------------------------------------- 시나리오 A

def test_scenario_a_analysis_handover(login, page: Page, server):
    """결과표 작성 → 캡처 붙여넣기 → 로그 블록 → 저장 → 다른 관제자가 그대로 보고 확인한다."""
    login()
    page.goto(server["base"] + "/handovers")
    page.get_by_role("button", name=re.compile("^인수인계$")).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("관계사 *").locator("option")).not_to_have_count(0, timeout=15000)
    dialog.get_by_label("제목 *").fill("E2E WAF 이상 요청 분석")
    editor = dialog.get_by_role("textbox", name=EDITOR)
    expect(editor).to_be_visible(timeout=20000)

    # ① 탐지 결과표 — 행 · 열을 정해 넣고 칸을 채운다
    editor.click()
    page.keyboard.type("탐지 결과 요약")
    page.keyboard.press("Enter")
    dialog.get_by_role("button", name="표 넣기").first.click()
    form = dialog.get_by_role("group", name="표 넣기")
    form.get_by_label("행 수").fill("2")
    form.get_by_label("열 수").fill("3")
    form.get_by_role("button", name="표 넣기").click()
    for i, text in enumerate(["항목", "탐지 내용", "조치", "WAF", "SQL Injection 의심", "차단"]):
        if i:
            page.keyboard.press("Tab")
        page.keyboard.type(text)
    # 표 안에서만 나오는 도구로 행을 늘린다
    expect(dialog.get_by_role("group", name="표 도구")).to_be_visible()
    dialog.get_by_role("button", name="아래에 행").click()
    page.keyboard.press("Tab")          # 마지막 칸에서 Tab → 새 행 첫 칸
    page.keyboard.type("IPS")
    expect(editor.locator("table tr")).to_have_count(3)

    # ② WAF 화면 캡처 붙여넣기(Ctrl+V)
    page.keyboard.press("Control+End")   # 표 다음 빈 문단으로
    paste_image(editor, png(), focus=False)
    expect(editor.locator("img")).to_have_count(1, timeout=15000)
    expect(dialog.get_by_text("그림 올리는 중")).to_have_count(0, timeout=15000)

    # ③ HTTP 로그 블록
    page.keyboard.press("Control+End")
    dialog.get_by_role("button", name="로그 · 코드 블록").click()
    page.keyboard.insert_text(HTTP_LOG)
    expect(editor.locator("pre")).to_contain_text("<script>alert")

    dialog.get_by_role("button", name="등록").click()
    expect(dialog).not_to_be_visible(timeout=20000)

    row = find_handover(server, "E2E WAF 이상 요청 분석")
    assert row["content_doc"] is not None
    assert "WAF | SQL Injection 의심 | 차단" in row["content"]
    assert "[그림]" in row["content"]
    assert HTTP_LOG in row["content"], "로그는 한 글자도 바뀌지 않고 저장돼야 한다"

    # ④ 다른 관제자(주간 근무자)가 연다 — 표 · 그림 · 로그가 그대로
    login("e2e_day", USER_PW)
    drawer = open_drawer(page, server, row["id"])
    view = drawer.locator(".rich-view").first
    expect(view.locator("table")).to_be_visible()
    expect(view.locator("td", has_text="SQL Injection 의심")).to_be_visible()
    img = view.locator("figure img")
    expect(img).to_be_visible(timeout=15000)
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=img.element_handle(), timeout=15000)
    code = view.locator(".code-block pre")
    expect(code).to_have_text(HTTP_LOG)
    assert not page.evaluate("() => window.__xss_ran === true")

    # ⑤ 인수 확인
    drawer.get_by_role("button", name=re.compile("확인\\(Ack\\)")).click()
    with api(server, "e2e_day", USER_PW) as c:
        expect_ack = c.get(f"/handovers/{row['id']}").json()["my_ack_state"]
    assert expect_ack == "ACKED"


# --------------------------------------------------------------------------- 시나리오 B

def test_scenario_b_comment_follow_up(login, page: Page, server):
    """기존 인계에 댓글로 분석표 · NDR 캡처를 붙이고 고친다 — 인수 확인은 그대로."""
    with api(server) as c:
        company = c.get("/companies").json()[0]["id"]
        made = c.post("/handovers", json={"company_id": company, "title": "E2E 댓글 후속 분석",
                                          "content": "NDR 추가 확인 필요"}).json()
    with api(server, "e2e_night", USER_PW) as c:
        assert c.post(f"/handovers/{made['id']}/acknowledge", json={}).status_code == 200

    login("e2e_night", USER_PW)
    drawer = open_drawer(page, server, made["id"])
    drawer.get_by_role("tab", name=re.compile("댓글")).click()
    box = drawer.get_by_role("textbox", name="새 댓글")
    expect(box).to_be_visible(timeout=20000)
    box.click()
    page.keyboard.type("NDR 추가 분석 결과")
    page.keyboard.press("Enter")
    paste_html(box, EXCEL_TABLE)
    expect(box.locator("table")).to_be_visible(timeout=10000)
    expect(box.locator("img")).to_have_count(0), "Excel 표는 그림이 아니라 표로 들어와야 한다"
    page.keyboard.press("Control+End")
    paste_image(box, png(120, 60, b"\xc0\x40\x20"), "ndr.png")
    expect(box.locator("img")).to_have_count(1, timeout=15000)
    drawer.get_by_role("button", name="댓글 등록").click()

    item = drawer.locator("li", has_text="NDR 추가 분석 결과")
    expect(item.locator("table td", has_text="내부 영향 확인")).to_be_visible(timeout=15000)
    expect(item.locator("figure img")).to_be_visible()

    # 고치기
    item.get_by_role("button", name="고치기").click()
    edit_box = drawer.get_by_role("textbox", name="댓글 고치기")
    expect(edit_box).to_be_visible(timeout=15000)
    edit_box.locator("p").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" (재확인)")
    drawer.get_by_role("button", name="저장").click()
    expect(drawer.get_by_text("(고침)")).to_be_visible(timeout=15000)
    expect(drawer.get_by_text("NDR 추가 분석 결과 (재확인)")).to_be_visible()

    # 그림 크게 보기
    drawer.locator("li", has_text="(재확인)").locator("figure button").click()
    box_dialog = page.get_by_role("dialog", name=re.compile("그림 크게 보기"))
    expect(box_dialog).to_be_visible()
    expect(box_dialog.get_by_role("link", name=re.compile("원본 받기"))).to_be_visible()
    page.keyboard.press("Escape")
    expect(box_dialog).not_to_be_visible()
    expect(drawer).to_be_visible(), "그림 창을 닫는 Esc 가 인수인계 상세까지 닫으면 안 된다"

    # 댓글을 쓰다가 Esc 를 눌러도 쓰던 글이 날아가지 않는다
    box = drawer.get_by_role("textbox", name="새 댓글")
    box.click()
    page.keyboard.type("쓰던 댓글")
    page.keyboard.press("Escape")
    expect(drawer).to_be_visible()
    expect(box).to_contain_text("쓰던 댓글")

    with api(server, "e2e_night", USER_PW) as c:
        after = c.get(f"/handovers/{made['id']}").json()
    assert after["current_version_no"] == made["current_version_no"], "댓글은 원문 버전을 바꾸지 않는다"
    assert after["my_ack_state"] == "ACKED", "댓글 때문에 인수 확인이 풀리면 안 된다"


# --------------------------------------------------------------------------- 시나리오 C

def test_scenario_c_legacy_plain_text(login, page: Page, server):
    """서식 없는 옛 글 → 그대로 보인다 → 일부만 굵게 → 저장 · 다시 보기 → 내보내기 · 복원."""
    legacy = "옛 방식 본문 첫 줄\n두 번째 줄 <b>태그처럼 보이는 글</b>"
    with api(server) as c:
        company = c.get("/companies").json()[0]["id"]
        made = c.post("/handovers", json={"company_id": company, "title": "E2E 옛 글 호환",
                                          "content": legacy}).json()
    assert made["content_doc"] is None

    login()
    drawer = open_drawer(page, server, made["id"])
    expect(drawer.get_by_text("두 번째 줄 <b>태그처럼 보이는 글</b>")).to_be_visible()

    drawer.get_by_role("button", name="수정").click()
    editor = drawer.get_by_role("textbox", name=EDITOR)
    expect(editor).to_be_visible(timeout=20000)
    editor.locator("p").first.click()
    page.keyboard.press("Home")
    page.keyboard.press("Shift+End")
    page.keyboard.press("Control+B")
    drawer.get_by_role("button", name=re.compile("^저장")).click()
    expect(drawer.locator(".rich-view strong", has_text="옛 방식 본문 첫 줄")).to_be_visible(timeout=15000)
    expect(drawer.get_by_text("두 번째 줄 <b>태그처럼 보이는 글</b>")).to_be_visible()

    with api(server) as c:
        now = c.get(f"/handovers/{made['id']}").json()
        assert now["content"] == legacy, "굵게만 바꿨으니 텍스트는 그대로"
        out = c.post("/export/handovers", json={}).json()
        book = c.get(f"/export/download/{out['download_token']}").content
    cells = [str(v) for ws in load_workbook(io.BytesIO(book), read_only=True).worksheets
             for r in ws.iter_rows(values_only=True) for v in r if v is not None]
    assert any("옛 방식 본문 첫 줄" in v for v in cells)
    assert not any('"type"' in v for v in cells), "Excel 에 서식 구조가 새면 안 된다"

    # 검색 · 버전 복원
    with api(server) as c:
        hits = c.post("/search/handovers", json={"q": "태그처럼 보이는", "page": 1, "size": 5}).json()
        assert made["id"] in [x["id"] for x in hits["items"]]
    drawer.get_by_role("tab", name="변경이력").click()
    drawer.get_by_role("button", name="복원").first.click()
    confirm = page.get_by_role("alertdialog")
    confirm.get_by_label(re.compile("복원 사유")).fill("E2E 옛 글로 되돌림")
    confirm.get_by_role("button", name="복원").click()
    expect(confirm).not_to_be_visible(timeout=10000)
    with api(server) as c:
        restored = c.get(f"/handovers/{made['id']}").json()
    assert restored["content_doc"] is None and restored["content"] == legacy


# --------------------------------------------------------------------------- 시나리오 D

def test_scenario_d_permissions_and_xss(login, page: Page, server):
    """그룹 제한 인계의 그림은 그룹 밖에서 목록 · 본문 · 그림 주소 어디로도 안 열린다."""
    with api(server) as c:
        company = c.get("/companies").json()[0]["id"]
        me = c.get("/auth/me").json()
        group = c.post("/groups", json={"name": "E2E 본문 그림 제한"}).json()
        mine = [g["id"] for g in c.get(f"/users/{me['id']}/groups").json()]
        c.put(f"/users/{me['id']}/groups", json={"group_ids": mine + [group["id"]],
                                                "default_group_id": mine[0] if mine else group["id"]})
        shot = c.post("/attachments/inline", files={"file": ("waf.png", png(), "image/png")}).json()
        secret = c.post("/handovers", json={
            "company_id": company, "title": "E2E 그룹 제한 그림", "visibility": "GROUPS",
            "group_ids": [group["id"]],
            "content_doc": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "내부 전용 분석"}]},
                {"type": "image", "attrs": {"src": shot["url"], "alt": "내부 화면"}}]}}).json()
        # XSS — 로그에 든 태그 · 스크립트는 글자로만 보여야 한다
        xss = c.post("/handovers", json={"company_id": company, "title": "E2E XSS 무해화", "content_doc": {
            "type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text",
                                                   "text": "<img src=x onerror=\"window.__xss_ran=true\">"}]},
                {"type": "codeBlock", "attrs": {"language": "http"}, "content": [
                    {"type": "text", "text": "<script>window.__xss_ran=true</script>"}]}]}}).json()
        bad = c.post("/handovers", json={"company_id": company, "title": "E2E 위험 링크", "content_doc": {
            "type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [
                {"type": "link", "attrs": {"href": "javascript:window.__xss_ran=true"}}]}]}]}})
        assert bad.status_code == 422, "javascript: 링크는 저장 자체가 안 된다"

    # 그룹 밖 사람(야간 근무자)
    login("e2e_night", USER_PW)
    page.goto(server["base"] + "/handovers")
    expect(page.get_by_text("E2E XSS 무해화").first).to_be_visible(timeout=20000)
    expect(page.get_by_text("E2E 그룹 제한 그림")).to_have_count(0)
    assert page.request.get(server["base"] + shot["url"]).status == 404, "그림 주소를 알아도 열리지 않는다"
    assert page.request.get(f"{server['base']}/api/v1/attachments/{shot['id']}/download").status == 404
    assert page.request.get(f"{server['base']}/api/v1/handovers/{secret['id']}").status == 404
    assert page.request.get(f"{server['base']}/api/v1/handovers/{secret['id']}/comments").status == 404

    drawer = open_drawer(page, server, xss["id"])
    expect(drawer.get_by_text('<img src=x onerror="window.__xss_ran=true">')).to_be_visible()
    expect(drawer.locator(".code-block pre")).to_have_text("<script>window.__xss_ran=true</script>")
    page.wait_for_timeout(500)
    assert page.evaluate("() => window.__xss_ran") is None, "본문의 태그가 실행되면 안 된다"
    assert drawer.locator(".rich-view img").count() == 0, "글로 쓴 <img> 는 그림이 되면 안 된다"

    # 권한 회수: 그룹에 넣었다가 빼면 그 즉시 그림이 닫힌다
    with api(server) as c:
        night = next(u for u in c.get("/users").json()["items"] if u["username"] == "e2e_night")
        before = [g["id"] for g in c.get(f"/users/{night['id']}/groups").json()]
        c.put(f"/users/{night['id']}/groups", json={"group_ids": before + [group["id"]]})
    assert page.request.get(server["base"] + shot["url"]).status == 200
    with api(server) as c:
        c.put(f"/users/{night['id']}/groups", json={"group_ids": before})
    assert page.request.get(server["base"] + shot["url"]).status == 404
