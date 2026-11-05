"""다른 탭에서 계정을 바꾼 뒤 이전 탭이 메모를 읽거나 쓰지 못한다."""
from tests.conftest import ANALYST_PW


def test_stale_tab_after_account_switch(analyst_client, users):
    client = analyst_client
    notes = "/api/v1/me/notes"
    stale_header = {"X-Expected-User-ID": str(users["analyst"]["id"])}
    assert client.get(notes, headers=stale_header).status_code == 200
    assert client.login("analyst2", ANALYST_PW).status_code == 200
    created = client.post(notes, json={"title": "두 번째 계정", "body": "개인 본문"})
    assert created.status_code == 201
    note = created.json()
    path = f"{notes}/{note['id']}"

    for method, url, options in [
        ("GET", notes, {}),
        ("GET", path, {}),
        ("POST", notes, {"json": {"title": "첫 번째 계정에서 쓰던 초안"}}),
        ("PATCH", path, {"json": {"body": "잘못된 수정", "expected_version": 1}}),
        ("DELETE", path, {"params": {"expected_version": 1}}),
    ]:
        response = client.request(method, url, headers=stale_header, **options)
        assert response.status_code == 412
        assert response.json()["error"] == "session_changed"
        assert response.json()["detail"] == {}
        assert note["body"] not in response.text

    current_header = {"X-Expected-User-ID": str(users["analyst2"]["id"])}
    assert client.get(notes, headers=current_header).json() == [note]
