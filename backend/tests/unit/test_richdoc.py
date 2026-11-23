"""서식 있는 본문 검사 — 허용 목록 밖은 하나도 통과하지 않는다."""
from __future__ import annotations

import pytest

from app.core import richdoc
from app.core.errors import ValidationFailed


def doc(*blocks):
    return {"type": "doc", "content": list(blocks)}


def p(*inline):
    return {"type": "paragraph", "content": list(inline)}


def t(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def img(n, **attrs):
    return {"type": "image", "attrs": {"src": f"/api/v1/attachments/{n}/inline", **attrs}}


def cell(text, kind="tableCell", **attrs):
    return {"type": kind, "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None, **attrs},
            "content": [p(t(text))]}


def table(*rows):
    return {"type": "table", "content": [{"type": "tableRow", "content": list(r)} for r in rows]}


WAF_TABLE = table(
    [cell("항목", "tableHeader"), cell("탐지 내용", "tableHeader"), cell("조치", "tableHeader")],
    [cell("WAF"), cell("SQL Injection 의심"), cell("차단")],
    [cell("IPS"), cell("동일 IP 반복 탐지"), cell("모니터링")],
)


# --------------------------------------------------------------------------- 통과해야 하는 것

class TestWhatTheEditorProducesPasses:
    def test_soc_analysis_document(self):
        d = doc(
            {"type": "heading", "attrs": {"level": 2}, "content": [t("WAF 이상 요청 분석")]},
            p(t("요약: "), t("차단 완료", {"type": "bold"}),
              t(" 색", {"type": "textStyle", "attrs": {"color": "#dc2626"}})),
            WAF_TABLE,
            img(12, alt="WAF 탐지 화면", width=75),
            {"type": "codeBlock", "attrs": {"language": "http"},
             "content": [t("GET /login.php?id=1' OR '1'='1 HTTP/1.1\nHost: a.example")]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"checked": True}, "content": [p(t("차단 확인"))]}]},
            p(t("근거", {"type": "link", "attrs": {"href": "https://intra.example/ticket/1",
                                                  "target": "_blank", "rel": "noopener", "class": None}})),
        )
        clean = richdoc.validate(d)
        assert clean["content"][0]["attrs"] == {"level": 2}
        link = clean["content"][-1]["content"][0]["marks"][0]
        assert link == {"type": "link", "attrs": {"href": "https://intra.example/ticket/1"}}, \
            "rel/target 은 저장하지 않는다 — 그릴 때 우리가 정한다"

    def test_merged_cells_and_column_widths(self):
        merged = table([cell("병합", colspan=2, colwidth=[120, 200])], [cell("a"), cell("b")])
        assert richdoc.validate(doc(merged))

    def test_null_default_attributes_are_dropped_not_rejected(self):
        clean = richdoc.validate(doc({"type": "paragraph", "attrs": {"textAlign": None},
                                      "content": [t("x")]}))
        assert "attrs" not in clean["content"][0]


# --------------------------------------------------------------------------- 막아야 하는 것

@pytest.mark.parametrize("bad", [
    # 허용하지 않는 요소
    doc({"type": "script", "content": [t("alert(1)")]}),
    doc({"type": "iframe", "attrs": {"src": "https://evil"}}),
    doc(p({"type": "mention", "attrs": {"id": "x"}})),
    # 링크로 스크립트 실행
    doc(p(t("x", {"type": "link", "attrs": {"href": "javascript:alert(1)"}}))),
    doc(p(t("x", {"type": "link", "attrs": {"href": " JaVaScRiPt:alert(1)"}}))),
    doc(p(t("x", {"type": "link", "attrs": {"href": "data:text/html,<script>alert(1)</script>"}}))),
    doc(p(t("x", {"type": "link", "attrs": {"href": "vbscript:x"}}))),
    doc(p(t("x", {"type": "link", "attrs": {"href": "file:///C:/Windows"}}))),
    # 외부 그림 자동 불러오기 · data: 그림(Base64 저장 금지)
    doc(img(1) | {"attrs": {"src": "https://evil.example/track.png"}}),
    doc({"type": "image", "attrs": {"src": "data:image/png;base64,iVBORw0KGgo="}}),
    doc({"type": "image", "attrs": {"src": "/api/v1/attachments/1/inline?x=<script>"}}),
    doc({"type": "image", "attrs": {"src": "/api/v1/attachments/1/download"}}),
    # 이벤트 · 스타일 속성 끼워 넣기
    doc({"type": "image", "attrs": {"src": "/api/v1/attachments/1/inline", "onerror": "alert(1)"}}),
    doc({"type": "paragraph", "attrs": {"style": "background:url(x)"}, "content": [t("x")]}),
    doc(p(t("x", {"type": "textStyle", "attrs": {"color": "red;background:url(//evil)"}}))),
    doc(p(t("x", {"type": "textStyle", "attrs": {"fontFamily": "x"}}))),
    doc(p(t("x", {"type": "highlight", "attrs": {"color": "expression(alert(1))"}}))),
    # 허용 범위 밖 값
    doc({"type": "heading", "attrs": {"level": 1}, "content": [t("H1")]}),
    doc(img(1, width=33)),
    doc({"type": "codeBlock", "attrs": {"language": "<img src=x onerror=alert(1)>"},
         "content": [t("x")]}),
    # 구조 어긋남
    doc(t("최상위에 글자")),
    doc(p(p(t("문단 안의 문단")))),
    doc({"type": "table", "content": [p(t("행이 아닌 것"))]}),
    {"type": "paragraph"},
    "<p>html</p>",
    doc(p({"type": "text", "text": ""})),
])
def test_rejected(bad):
    with pytest.raises(ValidationFailed):
        richdoc.validate(bad)


def test_too_deep_is_rejected():
    node = p(t("x"))
    for _ in range(richdoc.MAX_DEPTH + 2):
        node = {"type": "blockquote", "content": [node]}
    with pytest.raises(ValidationFailed):
        richdoc.validate(doc(node))


def test_too_many_images_is_rejected():
    with pytest.raises(ValidationFailed):
        richdoc.validate(doc(*[img(i) for i in range(1, richdoc.MAX_IMAGES + 2)]))


def test_script_text_is_kept_as_plain_text():
    """로그에 든 <script> 는 '글자'다 — 지우지도 실행하지도 않고 그대로 둔다."""
    log = '<script>alert(document.cookie)</script> "&amp;" \\x3c'
    clean = richdoc.validate(doc({"type": "codeBlock", "attrs": {"language": "log"},
                                  "content": [t(log)]}))
    assert clean["content"][0]["content"][0]["text"] == log
    assert richdoc.to_text(clean) == log


# --------------------------------------------------------------------------- 순수 텍스트

def test_plain_text_for_search_export_and_rag():
    d = richdoc.validate(doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [t("WAF 분석")]},
        WAF_TABLE,
        img(5, alt="탐지 화면"),
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [p(t("첫째"))]},
            {"type": "listItem", "content": [p(t("둘째"))]}]},
        {"type": "codeBlock", "content": [t("SELECT 1;\nSELECT 2;")]},
    ))
    text = richdoc.to_text(d)
    assert "WAF 분석" in text
    assert "WAF | SQL Injection 의심 | 차단" in text, "표의 한 행이 한 줄로, 칸은 ' | ' 로"
    assert "[그림: 탐지 화면]" in text
    assert "- 첫째\n- 둘째" in text
    assert "SELECT 1;\nSELECT 2;" in text
    assert "{" not in text and "type" not in text, "구조(JSON)가 텍스트에 새면 안 된다"


def test_image_ids_and_rewrite():
    d = doc(p(t("a")), img(3), img(9), img(3))
    assert richdoc.image_ids(d) == [3, 9]
    moved = richdoc.rewrite_images(d, {3: 30})
    assert richdoc.image_ids(moved) == [30, 9]
    assert richdoc.image_ids(d) == [3, 9], "원본은 그대로"


def test_from_text_round_trip():
    text = "첫 줄\n\n셋째 줄 <b>그대로</b>"
    assert richdoc.to_text(richdoc.validate(richdoc.from_text(text))) == text


# --------------------------------------------------------------------------- 재확인 판정(b)

class TestStyleOnlyChangesAreNotContentChanges:
    base = doc(p(t("차단 완료")), img(4, width=50),
               p(t("근거", {"type": "link", "attrs": {"href": "https://a.example"}})))

    def _same(self, other):
        return (richdoc.to_text(self.base) == richdoc.to_text(other)
                and richdoc.media_signature(self.base) == richdoc.media_signature(other))

    def test_bold_color_and_image_size_are_style(self):
        styled = doc(p(t("차단 완료", {"type": "bold"},
                         {"type": "textStyle", "attrs": {"color": "#dc2626"}})),
                     img(4, width=100),
                     p(t("근거", {"type": "link", "attrs": {"href": "https://a.example"}})))
        assert self._same(styled)

    def test_heading_level_is_style(self):
        a = doc({"type": "heading", "attrs": {"level": 2}, "content": [t("제목")]})
        b = doc({"type": "heading", "attrs": {"level": 3}, "content": [t("제목")]})
        assert richdoc.to_text(a) == richdoc.to_text(b)

    def test_text_change_is_content(self):
        assert not self._same(doc(p(t("차단 실패")), img(4, width=50),
                                  p(t("근거", {"type": "link", "attrs": {"href": "https://a.example"}}))))

    def test_swapped_image_is_content(self):
        assert not self._same(doc(p(t("차단 완료")), img(8, width=50),
                                  p(t("근거", {"type": "link", "attrs": {"href": "https://a.example"}}))))

    def test_changed_link_target_is_content(self):
        assert not self._same(doc(p(t("차단 완료")), img(4, width=50),
                                  p(t("근거", {"type": "link", "attrs": {"href": "https://b.example"}}))))
