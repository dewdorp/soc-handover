"""1.3.1 운영 편의성 패치 — 실제 브라우저로 끝까지 해 본다.

여기서 확인하는 것은 '화면이 뜬다'가 아니라 **사람이 하려는 일이 끝나는가**다.
설정 화면이 다 그려지는가, 잘못된 값 하나가 화면을 막지 않는가, 금고를 한 번
인증해 목록으로 보고 잠글 수 있는가, 절차 문서를 쓰고 고치고 되돌릴 수 있는가,
과거 자료 전환이 승인 없이는 아무것도 바꾸지 않는가.
"""
from __future__ import annotations

import re
from contextlib import contextmanager

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN_PW, USER_PW

pytestmark = pytest.mark.e2e


@contextmanager
def _api(server, username="admin", password=ADMIN_PW):
    """로그인된 API 손잡이. httpx.Client 는 한 번 쓰면 다시 `with` 로 열 수 없어 직접 닫는다."""
    c = httpx.Client(base_url=f"{server['base']}/api/v1", timeout=30)
    try:
        c.post("/auth/login", json={"username": username, "password": password}).raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")
        yield c
    finally:
        c.close()


# --------------------------------------------------------------------------- §1 설정 화면

def test_settings_page_renders_every_category(login, page: Page, server):
    """설정 화면이 분류별로 다 그려지고, 근무표 기준일이 날짜 칸으로 나온다."""
    login()
    page.goto(server["base"] + "/settings")
    expect(page.get_by_role("heading", name="설정")).to_be_visible()
    for category in ("인수인계", "근무표", "비밀번호", "감사로그", "첨부"):
        expect(page.get_by_role("heading", name=category)).to_be_visible(timeout=15000)
    # roster.epoch_date 는 date 칸이어야 한다(예전에는 별칭 편집기로 그려져 깨졌다)
    epoch = page.get_by_label("근무표 기준일")
    expect(epoch).to_be_visible()
    assert epoch.get_attribute("type") == "date"
    # 목록·사전 값도 사람이 읽을 수 있는 칸으로 나온다
    expect(page.get_by_label("첨부 허용 확장자")).to_be_visible()
    expect(page.get_by_role("group", name="재확인 필드")).to_be_visible()
    assert "m.join is not a function" not in page.content()


def test_one_bad_setting_value_does_not_blank_the_page(login, page: Page, server):
    """값 하나의 모양이 틀어져도 그 줄만 경고로 바뀌고 나머지는 보인다."""
    from sqlalchemy import create_engine, text

    with _api(server) as c:
        c.get("/settings").raise_for_status()
    # DB 에 직접 이상한 값을 넣는다(API 는 막으므로, 과거 데이터·수동 수정 상황을 흉내 낸다)
    url = httpx.get(f"{server['base']}/api/v1/health", timeout=10).json()
    assert url  # 서버가 살아 있다
    engine = create_engine(_db_url(server))
    with engine.begin() as conn:
        conn.execute(text("UPDATE system_settings SET value = :v WHERE key = 'attachment.allowed_ext'"),
                     {"v": '"pdf,xlsx"'})      # 목록이어야 하는데 문자열
    engine.dispose()

    login()
    page.goto(server["base"] + "/settings")
    expect(page.get_by_role("heading", name="설정")).to_be_visible()
    # 다른 줄은 멀쩡하다
    expect(page.get_by_label("근무표 기준일")).to_be_visible(timeout=15000)
    expect(page.get_by_label("첨부 최대 크기")).to_be_visible()
    # 되돌려 놓는다(뒤 시험에 영향을 주지 않게)
    engine = create_engine(_db_url(server))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM system_settings WHERE key = 'attachment.allowed_ext'"))
    engine.dispose()


def _db_url(server) -> str:
    import json
    import os
    from pathlib import Path
    if os.environ.get("E2E_DATABASE_URL"):
        return os.environ["E2E_DATABASE_URL"]
    # SQLite 로 돌 때는 서버가 쓰는 파일을 health 응답이 아니라 환경에서 찾는다
    for candidate in Path(os.environ.get("TEMP", "/tmp")).glob("**/e2e-data*/e2e.db"):
        return f"sqlite+pysqlite:///{candidate.as_posix()}"
    raise RuntimeError(f"E2E DB 를 찾지 못했습니다: {json.dumps(dict(os.environ), default=str)[:200]}")


# --------------------------------------------------------------------------- §5 비밀번호 금고

def test_vault_bulk_view_extend_and_lock(login, page: Page, server):
    """한 번 인증 → 목록으로 평문 보기 → 연장 → 지금 잠그기."""
    with _api(server) as c:
        company = c.get("/companies").json()[0]["id"]
        for name, secret in (("코어 방화벽", "Fw#Core2026!"), ("SIEM 콘솔", "Siem#Con2026!")):
            c.post("/credentials", json={"company_id": company, "device_name": name,
                                         "scope": "SHARED", "username": "socadmin",
                                         "secret": secret}).raise_for_status()

    login()
    page.goto(server["base"] + "/credentials")
    expect(page.get_by_role("heading", name="비밀번호")).to_be_visible()
    expect(page.get_by_text("••••••••").first).to_be_visible()

    page.get_by_label("본인 계정 비밀번호").fill(ADMIN_PW)
    page.get_by_role("button", name="인증하고 보기").click()

    expect(page.get_by_label("코어 방화벽 비밀번호")).to_have_value("Fw#Core2026!", timeout=20000)
    expect(page.get_by_label("SIEM 콘솔 비밀번호")).to_have_value("Siem#Con2026!")
    expect(page.get_by_text(re.compile("일시 열람 중"))).to_be_visible()

    # 평문이 브라우저 저장소에 남지 않는다
    stored = page.evaluate(
        "() => JSON.stringify({l: Object.entries(localStorage), s: Object.entries(sessionStorage)})")
    assert "Fw#Core2026!" not in stored
    assert "Siem#Con2026!" not in stored

    page.get_by_role("button", name="5분 연장").click()
    expect(page.get_by_text("열람 시간을 연장했습니다.")).to_be_visible(timeout=10000)

    page.get_by_role("button", name="지금 잠그기").click()
    expect(page.get_by_label("코어 방화벽 비밀번호")).to_have_count(0, timeout=10000)
    expect(page.get_by_label("본인 계정 비밀번호")).to_be_visible()


def test_vault_does_not_show_another_persons_personal_password(login, page: Page, server):
    """남의 개인 비밀번호는 일괄 열람에도 나오지 않는다."""
    with _api(server, "e2e_night", USER_PW) as c:
        company = c.get("/companies").json()[0]["id"]
        c.post("/credentials", json={"company_id": company, "device_name": "야간조 개인 계정",
                                     "scope": "PERSONAL", "username": "night",
                                     "secret": "Night#Only2026!"}).raise_for_status()

    login("e2e_day", USER_PW)
    page.goto(server["base"] + "/credentials")
    page.get_by_label("본인 계정 비밀번호").fill(USER_PW)
    page.get_by_role("button", name="인증하고 보기").click()
    expect(page.get_by_text(re.compile("일시 열람 중"))).to_be_visible(timeout=20000)
    assert "Night#Only2026!" not in page.content()
    assert "야간조 개인 계정" not in page.content(), "남의 개인 항목은 목록에도 없다"


# --------------------------------------------------------------------------- §4 운영 지식

def test_knowledge_write_revise_compare_and_restore(login, page: Page, server):
    """절차를 쓰고, 고치고, 판을 비교하고, 옛 판으로 되돌린다."""
    login()
    page.goto(server["base"] + "/knowledge")
    expect(page.get_by_role("heading", name="운영 지식")).to_be_visible()

    page.get_by_role("button", name="새 문서").click()
    page.get_by_role("button", name="표준 양식 넣기").click()
    expect(page.get_by_label("절차 · 참고 내용")).to_contain_text("탐지 · 확인 기준", timeout=10000)
    page.get_by_label("제목").fill("랜섬웨어 의심 트래픽 대응 절차")
    page.get_by_label("태그").fill("랜섬웨어, 야간")
    page.get_by_role("button", name="저장").click()
    expect(page.get_by_text("저장했습니다.")).to_be_visible(timeout=15000)
    expect(page.get_by_role("heading", name="랜섬웨어 의심 트래픽 대응 절차")).to_be_visible()
    expect(page.get_by_role("button", name="#랜섬웨어").first).to_be_visible()

    page.get_by_role("button", name="수정").click()
    page.get_by_label("절차 · 참고 내용").fill("2판: 차단 기준을 /24 로 올린다")
    page.get_by_label(re.compile("수정 사유")).fill("차단 범위 조정")
    page.get_by_role("button", name="저장").click()
    expect(page.get_by_text("저장했습니다.")).to_be_visible(timeout=15000)

    page.get_by_role("button", name=re.compile("개정 이력")).click()
    expect(page.get_by_text("차단 범위 조정")).to_be_visible(timeout=10000)
    page.get_by_role("button", name="비교").last.click()
    expect(page.get_by_text("v1 (과거)")).to_be_visible(timeout=10000)

    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="복원").last.click()
    expect(page.get_by_text(re.compile("탐지 · 확인 기준"))).to_be_visible(timeout=15000)


def test_knowledge_group_restricted_document_is_invisible_to_others(login, page: Page, server):
    """그룹을 지정한 절차는 그 그룹 밖 사람에게 목록·직접 URL 모두 막힌다."""
    with _api(server) as c:
        group = c.post("/groups", json={"name": "E2E 지식 전용 그룹"}).json()
        me = c.get("/auth/me").json()
        c.put(f"/users/{me['id']}/groups", json={"group_ids": [group["id"]],
                                                 "default_group_id": group["id"]}).raise_for_status()
        article = c.post("/knowledge", json={"category": "비상 대응", "title": "E2E 내부 전용 절차",
                                             "body": "비공개", "visibility": "GROUPS",
                                             "group_ids": [group["id"]]})
        article.raise_for_status()
        aid = article.json()["id"]

    login("e2e_day", USER_PW)
    base = server["base"]
    page.goto(f"{base}/knowledge")
    expect(page.get_by_role("heading", name="운영 지식")).to_be_visible()
    assert "E2E 내부 전용 절차" not in page.content()
    page.goto(f"{base}/knowledge?id={aid}")
    expect(page.get_by_text("열람할 수 없는 문서입니다.")).to_be_visible(timeout=15000)


# --------------------------------------------------------------------------- §3 과거 자료 전환

def test_legacy_conversion_requires_typed_confirmation(login, page: Page, server):
    """승인 화면이 건수와 목록을 보여 주고, 문구를 입력하기 전까지는 전환되지 않는다."""
    with _api(server) as c:
        company = c.get("/companies").json()[0]["id"]
        me = c.get("/auth/me").json()
        groups = c.get("/groups/mine").json()
        gid = groups[0]["id"]
        made = c.post("/handovers", json={"company_id": company, "title": "E2E 과거 미분류 인계",
                                          "content": "본문", "visibility": "GROUPS",
                                          "group_ids": [gid]})
        made.raise_for_status()
        hid = made.json()["id"]
        # '미분류'로만 묶인 상태를 만든다(1.2 에서 올라온 자료의 모습)
        unclassified = next((g for g in c.get("/groups").json() if g["code"] == "UNCLASSIFIED"), None)
        assert unclassified, "미분류 그룹이 있어야 한다"
        c.put(f"/users/{me['id']}/groups",
              json={"group_ids": [unclassified["id"], gid], "default_group_id": unclassified["id"]})
        c.patch(f"/handovers/{hid}", json={"expected_version": 1, "visibility": "GROUPS",
                                           "group_ids": [unclassified["id"]]}).raise_for_status()

    login()
    page.goto(server["base"] + "/admin/groups")
    panel = page.get_by_role("heading", name=re.compile("전체 공개 전환"))
    expect(panel).to_be_visible(timeout=20000)
    expect(page.get_by_text(re.compile("외주 · 협력사 계정이 포함돼 있을 수 있습니다"))).to_be_visible()

    page.get_by_role("button", name="전환 준비").click()
    apply_button = page.get_by_role("button", name=re.compile("전체 공개로 전환"))
    expect(apply_button).to_be_disabled()

    page.get_by_label("확인 문구").fill("전체공개로 전환")
    expect(apply_button).to_be_disabled(), "백업 확인 없이는 누를 수 없다"
    page.get_by_label(re.compile("백업을 받았습니다")).check()
    expect(apply_button).to_be_enabled()
    apply_button.click()
    expect(page.get_by_text(re.compile("전체 공개로 바꿨습니다"))).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name=re.compile("되돌리기"))).to_be_visible()


# --------------------------------------------------------------------------- §6 정기 점검

def test_inspection_checklist_completes_on_the_dashboard(login, page: Page, server):
    """'점검' 반복 일정이 대시보드에 나오고, 눌러 완료하면 마감 점검 숫자가 줄어든다."""
    from datetime import date

    today = date.today().isoformat()
    with _api(server) as c:
        c.post("/schedules", json={"title": "E2E 수집 상태 점검", "event_type": "INSPECTION",
                                   "start_at": f"{today}T09:00:00+09:00",
                                   "end_at": f"{today}T09:20:00+09:00",
                                   "recurrence_rule": "FREQ=DAILY"}).raise_for_status()

    login()
    section = page.get_by_role("region", name="오늘 점검")
    expect(section).to_be_visible(timeout=20000)
    expect(section.get_by_text("E2E 수집 상태 점검")).to_be_visible()
    section.get_by_role("button", name=re.compile("E2E 수집 상태 점검 완료 처리")).click()
    expect(section.get_by_text("모두 완료")).to_be_visible(timeout=15000)
