"""두 근무자가 같은 브라우저로 로그인해도 메모와 검색 결과를 공유하지 않는다."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import USER_PW

pytestmark = pytest.mark.e2e


def test_notes_between_shifts(login):
    page = login('e2e_day', USER_PW)
    page.get_by_role('link', name='내 메모', exact=True).click()
    notes = page.get_by_role('region', name='메모 목록')
    title = page.get_by_label('제목', exact=True)
    body = page.get_by_role('textbox', name='내용', exact=True)
    save = page.get_by_role('button', name='저장', exact=True)
    first = 'WAF 오탐 후보 확인'
    second = '22시 재점검 · 인증 실패 경보'
    for subject, content in [(first, '정상 로그인 요청이 차단됐는지 요청 시각과 탐지 규칙을 대조한다.'),
                             (second, '22:00에 인증 실패 건수를 다시 확인한다.\n반복된 출발지와 계정 잠금 여부를 함께 확인한다.')]:
        page.get_by_role('button', name='새 메모').click()
        title.fill(subject)
        body.fill(content)
        save.click()
        expect(notes.get_by_role('button', name=re.compile(re.escape(subject)))).to_be_visible()
    search = page.get_by_role('searchbox', name='메모 검색')
    search.fill('계정 잠금')
    expect(notes.get_by_role('button', name=re.compile(re.escape(first)))).to_have_count(0)
    expect(notes.get_by_role('button', name=re.compile(re.escape(second)))).to_be_visible()
    search.fill('waf')
    expect(notes.get_by_role('button', name=re.compile(re.escape(first)))).to_be_visible()
    search.fill('')
    page.reload()
    notes.get_by_role('button', name=re.compile(re.escape(second))).click()
    expect(body).to_have_value(re.compile('계정 잠금'))
    body.fill('22시 재점검 완료')
    save.click()
    expect(page.get_by_text('저장했습니다.', exact=True)).to_be_visible()
    page.get_by_role('button', name='삭제', exact=True).click()
    page.get_by_role('alertdialog').get_by_role('button', name='삭제', exact=True).click()
    expect(notes.get_by_role('button', name=re.compile(re.escape(second)))).to_have_count(0)
    title.fill('저장하지 않은 주간 메모')
    page.get_by_role('link', name='팀 일정', exact=True).click()
    dialog = page.get_by_role('alertdialog')
    expect(dialog).to_be_visible()
    dialog.get_by_role('button', name='취소').click()
    expect(title).to_have_value('저장하지 않은 주간 메모')
    page.get_by_role('button', name='로그아웃').click()
    expect(page).to_have_url(re.compile('/login$'))
    login('e2e_night', USER_PW)
    page.get_by_role('link', name='내 메모', exact=True).click()
    expect(notes.get_by_text('저장한 메모가 없습니다.')).to_be_visible()
    search.fill(first)
    expect(notes.get_by_text('검색 결과가 없습니다.')).to_be_visible()
    expect(title).to_have_value('')
    expect(body).to_have_value('')


def test_account_switch_clears_other_open_note_tab(login, server):
    page = login('e2e_day', USER_PW)
    page.get_by_role('link', name='내 메모', exact=True).click()
    old_title = '주간 교대 재확인 메모'
    page.get_by_role('textbox', name='제목', exact=True).fill(old_title)
    body = page.get_by_role('textbox', name='내용', exact=True)
    body.fill('주간 세션에서 열어 둔 내용')
    page.get_by_role('button', name='저장', exact=True).click()
    expect(page.get_by_text('저장했습니다.', exact=True)).to_be_visible()
    body.fill('저장 전 개인 초안')
    other = page.context.new_page()
    other.goto(server['base'])
    other.get_by_role('button', name='로그아웃').click()
    expect(other).to_have_url(re.compile('/login$'))
    expect(page.get_by_text(old_title, exact=True)).to_have_count(0)
    expect(page.get_by_role('textbox', name='내용', exact=True)).to_have_count(0)
    other.get_by_label('계정').fill('e2e_night')
    other.get_by_label('비밀번호').fill(USER_PW)
    other.get_by_role('button', name='로그인').click()
    other.get_by_role('link', name='내 메모', exact=True).click()
    expect(other.get_by_text(old_title, exact=True)).to_have_count(0)
    page.bring_to_front()
    expect(page.get_by_text(old_title, exact=True)).to_have_count(0)
    page.goto(server['base'] + '/my-work/notes')
    expect(page.get_by_text('저장한 메모가 없습니다.')).to_be_visible()
    expect(body).to_have_value('')
    stored = page.evaluate('() => JSON.stringify([localStorage, sessionStorage, location.href])')
    assert old_title not in stored and '저장 전 개인 초안' not in stored
    other.close()


def test_first_save_while_initial_list_is_loading(login):
    page = login('e2e_day', USER_PW)
    initial = []

    def hold_initial_list(route):
        if route.request.method == 'GET' and not initial:
            initial.append((route, route.fetch()))
        else:
            route.continue_()

    page.route('**/api/v1/me/notes', hold_initial_list)
    page.get_by_role('link', name='내 메모', exact=True).click()
    page.get_by_role('textbox', name='제목', exact=True).fill('지연된 목록 조회 중 작성')
    # The request is held until this test releases it. Pump the browser event loop.
    for _ in range(100):
        if initial:
            break
        page.wait_for_timeout(50)
    assert initial
    save = page.get_by_role('button', name='저장', exact=True)
    saved_before_list = save.is_enabled()
    if saved_before_list:
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/me/notes')):
            save.click()
    route, response = initial[0]
    route.fulfill(response=response)
    if not saved_before_list:
        save.click()
    notes = page.get_by_role('region', name='메모 목록')
    expect(notes.get_by_role('button', name=re.compile('지연된 목록 조회 중 작성'))).to_be_visible()
