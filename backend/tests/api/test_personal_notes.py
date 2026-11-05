"""개인 메모 소유권·입력·낙관적 잠금 통합 테스트."""
import pytest

from app.main import app
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient

NOTES = '/api/v1/me/notes'


def create(client, title, body=''):
    response = client.post(NOTES, json={'title': title, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_crud_and_updated_order(analyst_client):
    c = analyst_client
    first = create(c, '  야간 재점검  ', '22시에 확인')
    second = create(c, 'WAF 오탐')
    assert first['title'] == '야간 재점검' and first['version_no'] == 1
    assert [row['id'] for row in c.get(NOTES).json()] == [second['id'], first['id']]
    path = f"{NOTES}/{first['id']}"
    changed = c.patch(path, json={'expected_version': 1, 'body': '점검 완료'})
    assert changed.status_code == 200
    assert changed.json()['version_no'] == 2
    assert changed.json()['body'] == '점검 완료'
    assert changed.json()['created_at'] == first['created_at']
    assert c.get(path).json() == changed.json()
    assert c.get(NOTES).json()[0] == changed.json()
    assert c.patch(path, json={'expected_version': 1, 'title': '이전 창'}).status_code == 409
    assert c.delete(path, params={'expected_version': 1}).status_code == 409
    assert c.get(path).json() == changed.json()
    assert c.delete(path, params={'expected_version': 2}).status_code == 204
    assert c.get(path).status_code == 404
    assert c.get(NOTES).json() == [second]


@pytest.mark.parametrize('login,password', [('analyst2', ANALYST_PW), ('admin', ADMIN_PW)], ids=['analyst', 'admin'])
def test_foreign_ids_indistinguishable_from_missing(analyst_client, login, password):
    mine = create(analyst_client, '나만 보는 내용', '소유자만 열람')
    with ApiClient(app) as other:
        assert other.login(login, password).status_code == 200
        assert other.get(NOTES).json() == []
        search = other.post('/api/v1/search/global', json={'q': mine['title']})
        assert search.status_code == 200 and search.json()['hits'] == []
        theirs = create(other, '다른 사용자의 메모')
        assert other.get(NOTES).json() == [theirs]
        for method, kwargs in [('get', {}), ('patch', {'json': {'expected_version': 1, 'title': '변경'}}),
                               ('delete', {'params': {'expected_version': 1}})]:
            request = getattr(other, method)
            foreign = request(f"{NOTES}/{mine['id']}", **kwargs)
            missing = request(f"{NOTES}/{max(mine['id'], theirs['id']) + 1}", **kwargs)
            assert foreign.status_code == missing.status_code == 404
            foreign_error, missing_error = foreign.json(), missing.json()
            foreign_error.pop('request_id')
            missing_error.pop('request_id')
            assert foreign_error == missing_error
    assert analyst_client.get(NOTES).json() == [mine]


def test_validation_and_auth(analyst_client):
    with ApiClient(app) as guest:
        assert guest.get(NOTES).status_code == 401
    for fields in ({'title': ' \t '}, {'title': 'x' * 201}, {'title': 'x', 'body': 'x' * 50001}):
        assert analyst_client.post(NOTES, json=fields).status_code == 422
    response = analyst_client.post(NOTES, json={'title': '본문 생략'})
    assert response.status_code == 201 and response.json()['body'] == ''
    path = f"{NOTES}/{response.json()['id']}"
    for fields in ({'title': '버전 없음'}, {'expected_version': 1}, {'expected_version': 1, 'title': ' '}):
        assert analyst_client.patch(path, json=fields).status_code == 422
    assert analyst_client.delete(path).status_code == 422
