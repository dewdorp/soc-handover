"""서식 있는 본문(표 · 스크린샷 · 로그) — 저장 · 권한 · 재확인 · 옛 자료 호환.

여기서 지키는 선
  · 본문 구조는 허용 목록만 통과하고, 텍스트 칼럼은 서버가 다시 뽑는다(검색 · Excel · RAG).
  · 붙여 넣은 그림은 저장 전엔 올린 사람만, 저장 뒤엔 그 글을 볼 수 있는 사람만 본다.
  · 댓글은 인계 버전 · 인수 확인을 건드리지 않는다.
  · 서식만 바꾼 수정은 재확인을 일으키지 않는다(글 · 표 · 그림 · 링크가 바뀌면 일으킨다).
  · 서식 없는 옛 자료는 그대로 보이고, 고친 사람만 바꾼다.
"""
from __future__ import annotations

import io
import struct
import zlib
from datetime import timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.time import now
from app.main import app
from app.models.common import Attachment, AuditLog
from app.models.group import Group, UserGroup
from tests.conftest import ADMIN_PW, ANALYST_PW, ApiClient

H = "/api/v1/handovers"
A = "/api/v1/attachments"


def png(width: int = 3, height: int = 2, color: bytes = b"\x10\x80\xd0") -> bytes:
    raw = b"".join(b"\x00" + color * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _login(username: str, password: str) -> ApiClient:
    c = ApiClient(app)
    c.__enter__()
    assert c.login(username, password).status_code == 200
    return c


@pytest.fixture
def admin(users):
    c = _login("admin", ADMIN_PW)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def other(users):
    c = _login("analyst1", ANALYST_PW)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def cid(db):
    from app.models.reference import Company
    return db.scalar(select(Company.id).limit(1))


def _group(db, users, name, member="admin") -> int:
    g = Group(name=name, is_active=True)
    db.add(g)
    db.flush()
    db.add(UserGroup(user_id=users[member]["id"], group_id=g.id, is_default=False))
    db.commit()
    return g.id


def upload(client, data: bytes | None = None, name: str = "image.png"):
    return client.post(f"{A}/inline", files={"file": (name, data or png(), "image/png")})


# --------------------------------------------------------------------------- 문서 조립

def p(*inline):
    return {"type": "paragraph", "content": list(inline)}


def t(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def img(att_id, **attrs):
    return {"type": "image", "attrs": {"src": f"/api/v1/attachments/{att_id}/inline", **attrs}}


def cell(text, kind="tableCell"):
    return {"type": kind, "attrs": {"colspan": 1, "rowspan": 1}, "content": [p(t(text))]}


def waf_table():
    return {"type": "table", "content": [
        {"type": "tableRow", "content": [cell("항목", "tableHeader"), cell("탐지 내용", "tableHeader"),
                                         cell("분석 결과", "tableHeader"), cell("조치", "tableHeader")]},
        {"type": "tableRow", "content": [cell("WAF"), cell("SQL Injection 의심"),
                                         cell("반복 요청 확인"), cell("차단")]},
        {"type": "tableRow", "content": [cell("NDR"), cell("추가 통신 탐지"),
                                         cell("내부 영향 확인"), cell("조사 중")]},
    ]}


HTTP_LOG = ("GET /board.php?id=1%27%20OR%201=1--<script>alert(1)</script> HTTP/1.1\n"
            "Host: www.example.co.kr\nUser-Agent: sqlmap/1.7")


def analysis_doc(image_id: int | None = None):
    blocks = [
        {"type": "heading", "attrs": {"level": 2}, "content": [t("WAF 이상 요청 분석")]},
        waf_table(),
    ]
    if image_id:
        blocks.append(img(image_id, alt="WAF 탐지 화면", width=75))
    blocks.append({"type": "codeBlock", "attrs": {"language": "http"}, "content": [t(HTTP_LOG)]})
    blocks.append(p(t("결론: "), t("차단 완료", {"type": "bold"})))
    return {"type": "doc", "content": blocks}


def create(client, cid, doc=None, **over):
    body = {"company_id": cid, "title": over.pop("title", "WAF 이상 요청"), **over}
    if doc is not None:
        body["content_doc"] = doc
    r = client.post(H, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- 시나리오 A — 분석 인계

class TestScenarioA:
    def test_table_screenshot_and_log_round_trip(self, admin, other, cid):
        shot = upload(admin)
        assert shot.status_code == 201, shot.text
        shot = shot.json()
        assert shot["url"] == f"/api/v1/attachments/{shot['id']}/inline"

        row = create(admin, cid, analysis_doc(shot["id"]))
        # 텍스트 칼럼은 서버가 구조에서 다시 뽑는다 — 표 행 · 그림 자리 · 로그 원문이 들어 있다
        assert "WAF | SQL Injection 의심 | 반복 요청 확인 | 차단" in row["content"]
        assert "[그림: WAF 탐지 화면]" in row["content"]
        assert HTTP_LOG in row["content"], "로그는 한 글자도 바뀌지 않고 그대로"
        assert row["content_doc"]["content"][1]["type"] == "table"

        # 다음 교대자(다른 사람)가 그대로 본다
        seen = other.get(f"{H}/{row['id']}").json()
        assert seen["content_doc"] == row["content_doc"]
        pic = other.get(shot["url"])
        assert pic.status_code == 200, "저장된 그림은 글을 볼 수 있는 사람이 본다"
        assert pic.headers["content-type"] == "image/png"
        assert "no-store" in pic.headers["cache-control"]
        assert pic.headers["x-content-type-options"] == "nosniff"

        # 인수 확인
        ack = other.post(f"{H}/{row['id']}/acknowledge", json={})
        assert ack.status_code == 200, ack.text

    def test_table_cells_are_searchable(self, admin, cid):
        row = create(admin, cid, analysis_doc(), title="표 검색 확인")
        found = admin.post("/api/v1/search/handovers", json={"q": "내부 영향 확인", "page": 1, "size": 20})
        assert found.status_code == 200, found.text
        assert row["id"] in [x["id"] for x in found.json()["items"]], "표 칸의 글이 검색에 걸려야 한다"

    def test_excel_export_gets_plain_text_not_markup(self, admin, cid):
        row = create(admin, cid, analysis_doc(), title="엑셀 확인")
        out = admin.post("/api/v1/export/handovers", json={"ids": [row["id"]]})
        if out.status_code == 422:      # ids 로 고르는 방식이 없으면 전체 내보내기
            out = admin.post("/api/v1/export/handovers", json={})
        assert out.status_code == 200, out.text
        got = admin.get(f"/api/v1/export/download/{out.json()['download_token']}")
        wb = load_workbook(io.BytesIO(got.content), read_only=True)
        cells = [str(c) for ws in wb.worksheets for r in ws.iter_rows(values_only=True)
                 for c in r if c is not None]
        mine = [c for c in cells if "WAF | SQL Injection 의심" in c]
        assert mine, "표가 글로 들어가야 한다"
        assert all('"type"' not in c and "tableRow" not in c for c in cells), "구조(JSON)가 새면 안 된다"


# --------------------------------------------------------------------------- 시나리오 B — 댓글

class TestScenarioB:
    def test_comment_with_table_and_image_keeps_version_and_ack(self, admin, other, cid):
        row = create(admin, cid, analysis_doc(), title="댓글 확인")
        assert other.post(f"{H}/{row['id']}/acknowledge", json={}).status_code == 200
        before = other.get(f"{H}/{row['id']}").json()
        assert before["my_ack_state"] == "ACKED"

        shot = upload(other).json()
        doc = {"type": "doc", "content": [p(t("NDR 추가 분석")), waf_table(),
                                          img(shot["id"], alt="NDR 캡처")]}
        made = other.post(f"{H}/{row['id']}/comments", json={"body_doc": doc})
        assert made.status_code == 201, made.text
        comment = made.json()
        assert "NDR 추가 분석" in comment["body"] and "[그림: NDR 캡처]" in comment["body"]
        assert comment["body_doc"]["content"][1]["type"] == "table"

        edited = other.patch(f"/api/v1/handover-comments/{comment['id']}",
                             json={"body_doc": {"type": "doc", "content": [p(t("NDR 추가 분석 — 수정"))]}})
        assert edited.status_code == 200, edited.text
        assert edited.json()["is_edited"] is True

        after = other.get(f"{H}/{row['id']}").json()
        assert after["current_version_no"] == before["current_version_no"], "댓글은 원문 버전을 바꾸지 않는다"
        assert after["my_ack_state"] == "ACKED", "댓글 때문에 인수 확인이 풀리면 안 된다"

        # 댓글 그림도 인계 권한을 따른다 — 같은 인계를 보는 작성자에게 보인다
        assert admin.get(shot["url"]).status_code == 200

    def test_plain_comment_still_works(self, admin, cid):
        row = create(admin, cid, title="옛 댓글")
        made = admin.post(f"{H}/{row['id']}/comments", json={"body": "그냥 글"})
        assert made.status_code == 201 and made.json()["body_doc"] is None

    def test_empty_comment_rejected(self, admin, cid):
        row = create(admin, cid, title="빈 댓글")
        assert admin.post(f"{H}/{row['id']}/comments", json={"body": "  "}).status_code == 422


# --------------------------------------------------------------------------- 재확인(b) · 버전

class TestReackOnlyForContent:
    def _acked(self, admin, other, cid, doc):
        row = create(admin, cid, doc, title="재확인 판정")
        assert other.post(f"{H}/{row['id']}/acknowledge", json={}).status_code == 200
        return row

    def _edit(self, admin, row, doc):
        r = admin.patch(f"{H}/{row['id']}", json={"expected_version": row["current_version_no"],
                                                 "content_doc": doc})
        assert r.status_code == 200, r.text
        return r.json()

    def test_style_only_edit_makes_a_version_but_no_reack(self, admin, other, cid):
        base = {"type": "doc", "content": [p(t("차단 완료"))]}
        row = self._acked(admin, other, cid, base)
        styled = {"type": "doc", "content": [p(t("차단 완료", {"type": "bold"},
                                                 {"type": "textStyle", "attrs": {"color": "#dc2626"}}))]}
        out = self._edit(admin, row, styled)
        assert out["current_version_no"] == row["current_version_no"] + 1, "서식 변경도 버전은 남는다"
        assert other.get(f"{H}/{row['id']}").json()["my_ack_state"] == "ACKED", \
            "굵게 · 색만 바꿨는데 다시 확인하게 하면 안 된다"

    def test_text_edit_requires_reack(self, admin, other, cid):
        row = self._acked(admin, other, cid, {"type": "doc", "content": [p(t("차단 완료"))]})
        self._edit(admin, row, {"type": "doc", "content": [p(t("차단 실패"))]})
        assert other.get(f"{H}/{row['id']}").json()["my_ack_state"] == "REACK_REQUIRED"

    def test_table_cell_edit_requires_reack(self, admin, other, cid):
        row = self._acked(admin, other, cid, analysis_doc())
        doc = analysis_doc()
        doc["content"][1]["content"][1]["content"][3] = cell("허용")
        self._edit(admin, row, doc)
        assert other.get(f"{H}/{row['id']}").json()["my_ack_state"] == "REACK_REQUIRED"

    def test_new_image_requires_reack(self, admin, other, cid):
        row = self._acked(admin, other, cid, {"type": "doc", "content": [p(t("캡처 첨부 예정"))]})
        shot = upload(admin).json()
        self._edit(admin, row, {"type": "doc", "content": [p(t("캡처 첨부 예정")), img(shot["id"])]})
        assert other.get(f"{H}/{row['id']}").json()["my_ack_state"] == "REACK_REQUIRED"

    def test_image_resize_is_style(self, admin, other, cid):
        shot = upload(admin).json()
        row = self._acked(admin, other, cid, {"type": "doc", "content": [img(shot["id"], width=50)]})
        self._edit(admin, row, {"type": "doc", "content": [img(shot["id"], width=100)]})
        assert other.get(f"{H}/{row['id']}").json()["my_ack_state"] == "ACKED"

    def test_restore_brings_back_the_table(self, admin, cid):
        row = create(admin, cid, analysis_doc(), title="복원 확인")
        admin.patch(f"{H}/{row['id']}", json={"expected_version": 1,
                                             "content_doc": {"type": "doc", "content": [p(t("표 지움"))]}})
        back = admin.post(f"{H}/{row['id']}/versions/1/restore",
                          json={"expected_version": 2, "change_reason": "표 되살리기"})
        assert back.status_code == 200, back.text
        assert back.json()["content_doc"] == row["content_doc"], "복원하면 표 구조가 그대로 돌아온다"
        assert "WAF | SQL Injection 의심" in back.json()["content"]


# --------------------------------------------------------------------------- 시나리오 C — 옛 자료

class TestScenarioCLegacy:
    def test_plain_text_handover_stays_plain(self, admin, cid):
        row = create(admin, cid, content="옛 방식 본문\n두 번째 줄")
        assert row["content_doc"] is None and row["content"] == "옛 방식 본문\n두 번째 줄"

    def test_other_field_edit_by_old_client_keeps_formatting(self, admin, cid):
        """옛 클라이언트가 content 를 같은 값으로 함께 보내도 서식이 날아가면 안 된다."""
        row = create(admin, cid, analysis_doc(), title="서식 유지")
        out = admin.patch(f"{H}/{row['id']}", json={"expected_version": 1, "content": row["content"],
                                                   "is_important": True}).json()
        assert out["content_doc"] == row["content_doc"]

    def test_old_client_changing_text_drops_formatting(self, admin, cid):
        row = create(admin, cid, analysis_doc(), title="텍스트로 덮기")
        out = admin.patch(f"{H}/{row['id']}", json={"expected_version": 1,
                                                   "content": "옛 화면에서 고친 글"}).json()
        assert out["content_doc"] is None and out["content"] == "옛 화면에서 고친 글"

    def test_plain_text_converted_when_edited_in_new_editor(self, admin, cid):
        row = create(admin, cid, content="일부만 바꿀 글")
        doc = {"type": "doc", "content": [p(t("일부만 "), t("바꿀", {"type": "bold"}), t(" 글"))]}
        out = admin.patch(f"{H}/{row['id']}", json={"expected_version": 1, "content_doc": doc}).json()
        assert out["content"] == "일부만 바꿀 글" and out["content_doc"] is not None
        versions = admin.get(f"{H}/{row['id']}/versions").json()
        assert len(versions) == 2


# --------------------------------------------------------------------------- 시나리오 D — 보안 · 권한

class TestScenarioDSecurity:
    def test_group_restricted_image_is_closed_to_other_groups(self, admin, other, users, db, cid):
        gid = _group(db, users, "본문 그림 제한 그룹")
        shot = upload(admin).json()
        row = create(admin, cid, analysis_doc(shot["id"]), title="제한 인계",
                     visibility="GROUPS", group_ids=[gid])
        assert other.get(f"{H}/{row['id']}").status_code == 404
        assert other.get(shot["url"]).status_code == 404, "그림 주소를 알아도 볼 수 없다"
        assert other.get(f"{A}/{shot['id']}/download").status_code == 404
        listed = other.post("/api/v1/search/handovers", json={"q": "SQL Injection", "page": 1, "size": 50})
        assert row["id"] not in [x["id"] for x in listed.json()["items"]]

    def test_access_revoked_immediately(self, admin, other, users, db, cid):
        gid = _group(db, users, "회수 확인 그룹", member="analyst")
        db.add(UserGroup(user_id=users["admin"]["id"], group_id=gid, is_default=False))
        db.commit()
        shot = upload(admin).json()
        create(admin, cid, analysis_doc(shot["id"]), title="회수 확인",
               visibility="GROUPS", group_ids=[gid])
        assert other.get(shot["url"]).status_code == 200
        assert admin.put(f"/api/v1/users/{users['analyst']['id']}/groups",
                         json={"group_ids": []}).status_code == 200
        assert other.get(shot["url"]).status_code == 404, "소속을 빼는 즉시 그림도 닫힌다(캐시 없음)"

    def test_draft_image_is_visible_only_to_uploader(self, admin, other):
        shot = upload(admin).json()
        assert admin.get(shot["url"]).status_code == 200
        assert other.get(shot["url"]).status_code == 404, "저장 전 그림은 올린 사람만"

    def test_draft_image_original_download_only_for_uploader(self, admin, other):
        """편집기의 '원본 받기'는 저장 전에도 누른다 — 올린 사람만 받고, 감사에 남는다."""
        shot = upload(admin).json()
        got = admin.get(f"{A}/{shot['id']}/download")
        assert got.status_code == 200, got.text
        assert got.content.startswith(b"\x89PNG")
        assert other.get(f"{A}/{shot['id']}/download").status_code == 404

    def test_cannot_embed_someone_elses_draft(self, admin, other, cid):
        shot = upload(admin).json()
        r = other.post(H, json={"company_id": cid, "title": "남의 초안",
                                "content_doc": {"type": "doc", "content": [img(shot["id"])]}})
        assert r.status_code == 422, r.text

    def test_cannot_copy_an_image_from_a_handover_i_cannot_see(self, admin, other, users, db, cid):
        gid = _group(db, users, "복사 차단 그룹")
        shot = upload(admin).json()
        create(admin, cid, analysis_doc(shot["id"]), title="볼 수 없는 원본",
               visibility="GROUPS", group_ids=[gid])
        r = other.post(H, json={"company_id": cid, "title": "번호로 끌어오기",
                                "content_doc": {"type": "doc", "content": [img(shot["id"])]}})
        assert r.status_code == 422, "볼 수 없는 글의 그림 번호를 넣어 끌어올 수 없다"

    def test_copy_paste_between_visible_handovers_copies_the_image(self, admin, other, cid):
        shot = upload(admin).json()
        first = create(admin, cid, analysis_doc(shot["id"]), title="원본")
        second = create(other, cid, {"type": "doc", "content": [img(shot["id"], alt="복사")]},
                        title="붙여넣기")
        new_src = second["content_doc"]["content"][0]["attrs"]["src"]
        assert new_src != shot["url"], "다른 글의 그림은 복사본으로 묶는다"
        assert other.get(new_src).status_code == 200
        assert first["content_doc"]["content"][2]["attrs"]["src"] == shot["url"], "원본은 그대로"

    @pytest.mark.parametrize("bad", [
        {"type": "doc", "content": [{"type": "script", "content": [{"type": "text", "text": "x"}]}]},
        {"type": "doc", "content": [p(t("x", {"type": "link", "attrs": {"href": "javascript:alert(1)"}}))]},
        {"type": "doc", "content": [{"type": "image", "attrs": {"src": "https://evil.example/a.png"}}]},
        {"type": "doc", "content": [{"type": "image", "attrs": {"src": "data:image/png;base64,AAAA"}}]},
        {"type": "doc", "content": [{"type": "paragraph", "attrs": {"style": "x"}, "content": [t("x")]}]},
        "<p onclick=alert(1)>html</p>",
    ])
    def test_unsafe_documents_rejected(self, admin, cid, bad):
        r = admin.post(H, json={"company_id": cid, "title": "XSS", "content_doc": bad})
        assert r.status_code == 422, r.text

    def test_script_in_log_is_kept_as_text(self, admin, other, cid):
        row = create(admin, cid, analysis_doc(), title="로그 그대로")
        code = other.get(f"{H}/{row['id']}").json()["content_doc"]["content"][2]
        assert code["type"] == "codeBlock" and code["content"][0]["text"] == HTTP_LOG

    @pytest.mark.parametrize("name,data", [
        ("evil.png", b"<html><script>alert(1)</script></html>"),
        ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        ("note.txt", b"plain text"),
    ])
    def test_non_images_are_refused(self, admin, name, data):
        assert upload(admin, data, name).status_code == 422

    def test_inline_images_are_not_listed_or_deletable_as_attachments(self, admin, cid):
        shot = upload(admin).json()
        row = create(admin, cid, analysis_doc(shot["id"]), title="첨부 목록 분리")
        listed = admin.get(A, params={"entity_type": "HANDOVER", "entity_id": row["id"]}).json()
        assert shot["id"] not in [x["id"] for x in listed], "본문 그림은 첨부 목록에 나오지 않는다"
        assert admin.delete(f"{A}/{shot['id']}").status_code in (403, 422), \
            "본문 그림은 옛 버전 복원에 필요해 따로 지우지 않는다"

    def test_audit_does_not_store_the_document(self, admin, db, cid):
        row = create(admin, cid, analysis_doc(), title="감사 요약")
        db.expire_all()
        log = db.scalars(select(AuditLog).where(AuditLog.action == "HANDOVER_CREATE",
                                                AuditLog.resource_id == str(row["id"]))).first()
        stored = log.after_value["content_doc"]
        assert set(stored) == {"nodes", "images", "tables", "code_blocks"}, stored
        assert stored["tables"] == 1 and stored["code_blocks"] == 1


# --------------------------------------------------------------------------- 초안 정리

def test_stale_drafts_are_purged_with_their_files(admin, db, users):
    from app.services import attachment_service

    shot = upload(admin).json()
    att = db.get(Attachment, shot["id"])
    path = attachment_service.file_path(att)
    att.created_at = now() - timedelta(hours=25)
    db.commit()
    assert attachment_service.purge_stale_drafts(db) >= 1
    db.commit()
    db.expire_all()
    assert db.get(Attachment, shot["id"]).is_deleted is True
    assert not path.exists(), "파일까지 지운다"
    assert admin.get(shot["url"]).status_code == 404


def test_bound_images_are_never_purged(admin, db, cid):
    from app.services import attachment_service

    shot = upload(admin).json()
    create(admin, cid, analysis_doc(shot["id"]), title="묶인 그림")
    att = db.get(Attachment, shot["id"])
    att.created_at = now() - timedelta(days=30)
    db.commit()
    attachment_service.purge_stale_drafts(db)
    db.commit()
    assert admin.get(shot["url"]).status_code == 200


# --------------------------------------------------------------------------- 운영 지식 · 할일

def test_knowledge_doc_and_revision_restore(admin, other):
    shot = upload(admin).json()
    made = admin.post("/api/v1/knowledge", json={"category": "탐지·분석", "title": "SQLi 대응 절차",
                                                 "body_doc": analysis_doc(shot["id"])})
    assert made.status_code == 201, made.text
    art = made.json()
    assert "WAF | SQL Injection 의심" in art["body"]
    assert other.get(shot["url"]).status_code == 200, "공개 문서의 그림은 모두가 본다"

    admin.patch(f"/api/v1/knowledge/{art['id']}",
                json={"version_no": 1, "body_doc": {"type": "doc", "content": [p(t("간단히"))]}})
    v1 = admin.get(f"/api/v1/knowledge/{art['id']}/revisions/1").json()
    assert v1["body_doc"] == art["body_doc"], "개정 이력에 서식 구조도 남는다"
    back = admin.post(f"/api/v1/knowledge/{art['id']}/revisions/1/restore").json()
    assert back["body_doc"] == art["body_doc"]


def test_task_description_and_comment_docs(admin):
    made = admin.post("/api/v1/tasks", json={"title": "서식 할일", "description_doc": analysis_doc()})
    assert made.status_code == 201, made.text
    task = made.json()
    assert "차단 완료" in task["description"] and task["description_doc"] is not None
    c = admin.post(f"/api/v1/tasks/{task['id']}/comments",
                   json={"body_doc": {"type": "doc", "content": [p(t("후속 조치 완료"))]}})
    assert c.status_code == 201, c.text
    assert c.json()["body"] == "후속 조치 완료"


def test_rag_cases_read_plain_text(admin, cid):
    create(admin, cid, analysis_doc(), title="RAG 텍스트 확인", status_code="DONE")
    cases = admin.get("/api/v1/rag/cases", params={"limit": 50})
    assert cases.status_code == 200, cases.text
    blob = cases.text
    assert "tableRow" not in blob and '\\"type\\"' not in blob, "RAG 에 서식 코드가 섞이면 안 된다"
