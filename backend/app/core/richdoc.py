"""서식 있는 본문(리치 텍스트) — 저장 형식 검사 · 순수 텍스트 뽑기 · 그림 목록.

왜 HTML 이 아니라 구조(JSON)인가
  HTML 을 받아 저장하면 '무엇이 실행되는가'를 끝없이 걸러야 한다(속성 · 이벤트 · CSS ·
  인코딩 우회). 편집기(Tiptap/ProseMirror)가 쓰는 **문서 구조**를 받고, 여기서 정한
  **허용 목록 밖은 전부 거절**하면 실행될 수 있는 것이 애초에 들어오지 않는다. 화면도
  이 구조를 React 요소로 직접 그리므로 HTML 문자열을 끼워 넣는 곳이 없다.

기존 텍스트 칼럼과의 관계
  본문마다 `<이름>` (텍스트) 옆에 `<이름>_doc` (이 구조)을 둔다. 텍스트 칼럼은 **이
  모듈이 구조에서 다시 뽑은 순수 텍스트**다 — 검색 · Excel · RAG · 버전 비교 · 옛 API 가
  지금처럼 그것을 읽는다. 클라이언트가 보낸 텍스트는 믿지 않는다.
  `_doc` 이 비어 있으면 서식 없는 옛 글이고, 텍스트를 그대로 보여 준다.

재확인 판정 (사용자 결정 2026-11-23: '글 · 표 · 그림이 바뀔 때만')
  굵게 · 기울임 · 밑줄 · 색 · 강조 · 제목 크기 · 그림/열 너비만 바뀐 것은 재확인 대상이
  아니다. 순수 텍스트(표 칸 · 목록 표시 포함)와 그림 · 링크 주소가 그대로면 '내용은 같다'.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.errors import ValidationFailed

# --------------------------------------------------------------------------- 허용 목록

#: 그림 주소는 이 형태만 받는다 — 외부 주소 · data: · javascript: 는 모두 거절.
INLINE_IMAGE_SRC = re.compile(r"^/api/v1/attachments/(\d{1,12})/inline$")

#: 링크로 받는 주소의 시작. 그 밖(javascript: · data: · vbscript: · file: …)은 거절.
LINK_PROTOCOLS = ("http://", "https://", "mailto:")

#: 글자색 · 강조색은 정해 둔 것만. 아무 CSS 값이나 받으면 style 로 무엇이든 넣을 수 있다.
TEXT_COLORS = frozenset({"#dc2626", "#ea580c", "#16a34a", "#2563eb", "#7c3aed", "#6b7280"})
HIGHLIGHT_COLORS = frozenset({"#fef08a", "#fecaca", "#bbf7d0", "#bfdbfe"})

#: 코드 블록 언어 표시(보기 좋게 이름을 붙이는 데만 쓴다 — 실행하지 않는다)
CODE_LANGUAGES = frozenset({"", "plain", "log", "http", "json", "sql", "powershell", "bash",
                            "regex", "xml", "python"})

#: 그림 너비(화면 비율 %). 자유 입력을 받지 않는다.
IMAGE_WIDTHS = frozenset({25, 50, 75, 100})

#: 노드 종류별로 받을 수 있는 속성과 그 검사.
_NODE_ATTRS: dict[str, dict[str, Any]] = {
    "doc": {},
    "paragraph": {},
    "text": {},
    "hardBreak": {},
    "horizontalRule": {},
    "heading": {"level": lambda v: v in (2, 3)},
    "bulletList": {},
    "orderedList": {"start": lambda v: isinstance(v, int) and 1 <= v <= 10_000,
                    "type": lambda v: v in (None, "1")},
    "listItem": {},
    "taskList": {},
    "taskItem": {"checked": lambda v: isinstance(v, bool)},
    "blockquote": {},
    "codeBlock": {"language": lambda v: v is None or v in CODE_LANGUAGES},
    "image": {"src": lambda v: isinstance(v, str) and bool(INLINE_IMAGE_SRC.match(v)),
              "alt": lambda v: v is None or (isinstance(v, str) and len(v) <= 300),
              "title": lambda v: v is None or (isinstance(v, str) and len(v) <= 300),
              "width": lambda v: v is None or v in IMAGE_WIDTHS},
    "table": {},
    "tableRow": {},
    "tableHeader": {"colspan": lambda v: isinstance(v, int) and 1 <= v <= 50,
                    "rowspan": lambda v: isinstance(v, int) and 1 <= v <= 500,
                    "colwidth": lambda v: v is None or (isinstance(v, list) and len(v) <= 50 and all(
                        isinstance(x, int) and 20 <= x <= 2000 for x in v))},
}
_NODE_ATTRS["tableCell"] = _NODE_ATTRS["tableHeader"]

#: 이 노드 안에 들어갈 수 있는 자식. 구조가 어긋나면 화면이 이상하게 그려지므로 막는다.
_INLINE = frozenset({"text", "hardBreak", "image"})
_BLOCK = frozenset({"paragraph", "heading", "bulletList", "orderedList", "taskList",
                    "blockquote", "codeBlock", "horizontalRule", "table", "image"})
_CHILDREN: dict[str, frozenset[str]] = {
    "doc": _BLOCK,
    "paragraph": _INLINE,
    "heading": _INLINE,
    "bulletList": frozenset({"listItem"}),
    "orderedList": frozenset({"listItem"}),
    "listItem": _BLOCK,
    "taskList": frozenset({"taskItem"}),
    "taskItem": _BLOCK,
    "blockquote": _BLOCK,
    "codeBlock": frozenset({"text"}),
    "table": frozenset({"tableRow"}),
    "tableRow": frozenset({"tableHeader", "tableCell"}),
    "tableHeader": _BLOCK,
    "tableCell": _BLOCK,
    "text": frozenset(), "hardBreak": frozenset(), "horizontalRule": frozenset(),
    "image": frozenset(),
}

_MARK_ATTRS: dict[str, dict[str, Any]] = {
    "bold": {}, "italic": {}, "underline": {}, "strike": {}, "code": {},
    "link": {"href": lambda v: isinstance(v, str) and len(v) <= 2000
             and v.strip().lower().startswith(LINK_PROTOCOLS),
             # 편집기가 덧붙이는 값. 우리가 그릴 때 정하므로 받기만 하고 버린다.
             "target": lambda v: True, "rel": lambda v: True, "class": lambda v: True},
    "textStyle": {"color": lambda v: v is None or v in TEXT_COLORS},
    "highlight": {"color": lambda v: v is None or v in HIGHLIGHT_COLORS},
}
#: 그릴 때 쓰지 않는 링크 속성 — 저장하지 않는다(우리가 rel/target 을 정해서 붙인다).
_DROP_LINK_ATTRS = frozenset({"target", "rel", "class"})

#: 크기 상한. 넘으면 저장하지 않는다(화면 · DB · 검색을 함께 지킨다).
MAX_DEPTH = 30
MAX_NODES = 40_000
MAX_TEXT = 500_000          # 순수 텍스트 기준 글자 수
MAX_JSON_BYTES = 2_000_000  # 저장할 구조의 크기
MAX_IMAGES = 100


def _fail(message: str, **detail: Any) -> ValidationFailed:
    return ValidationFailed(f"본문 형식이 올바르지 않습니다: {message}", detail={"field": "doc", **detail})


# --------------------------------------------------------------------------- 검사

def validate(doc: Any) -> dict[str, Any]:
    """허용 목록으로 검사하고 **정리된 사본**을 돌려준다. 하나라도 어긋나면 거절한다.

    고쳐 주지 않고 거절하는 이유: 몰래 지운 부분이 생기면 쓴 사람은 저장된 줄 알고
    교대자는 다른 내용을 본다. 편집기가 만든 문서는 여기를 그대로 통과한다.
    """
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise _fail("최상위는 doc 이어야 합니다.")
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise _fail("본문이 너무 큽니다. 나눠서 저장하십시오.", limit_bytes=MAX_JSON_BYTES)
    counter = {"nodes": 0, "text": 0, "images": 0}
    clean = _node(doc, parent=None, depth=0, counter=counter)
    if counter["text"] > MAX_TEXT:
        raise _fail("글이 너무 깁니다.", limit_chars=MAX_TEXT)
    if counter["images"] > MAX_IMAGES:
        raise _fail(f"그림은 한 본문에 {MAX_IMAGES}개까지 넣을 수 있습니다.")
    return clean


def _node(node: Any, *, parent: str | None, depth: int, counter: dict[str, int]) -> dict[str, Any]:
    if depth > MAX_DEPTH:
        raise _fail("구조가 너무 깊습니다.")
    counter["nodes"] += 1
    if counter["nodes"] > MAX_NODES:
        raise _fail("구성 요소가 너무 많습니다.")
    if not isinstance(node, dict):
        raise _fail("구성 요소의 모양이 올바르지 않습니다.")
    kind = node.get("type")
    if kind not in _NODE_ATTRS:
        raise _fail(f"허용하지 않는 요소입니다: {str(kind)[:40]}", node=str(kind)[:40])
    if parent is not None and kind not in _CHILDREN[parent]:
        raise _fail(f"{parent} 안에 {kind} 를 둘 수 없습니다.")

    out: dict[str, Any] = {"type": kind}
    attrs = node.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise _fail("속성의 모양이 올바르지 않습니다.")
    allowed = _NODE_ATTRS[kind]
    clean_attrs: dict[str, Any] = {}
    for key, value in attrs.items():
        if key not in allowed:
            # 편집기가 붙이는 null 기본값(예: textAlign: null)은 조용히 버린다. 값이 있으면 거절.
            if value is None:
                continue
            raise _fail(f"{kind} 에 허용하지 않는 속성입니다: {str(key)[:40]}")
        if not allowed[key](value):
            raise _fail(f"{kind}.{key} 값이 허용 범위 밖입니다.")
        if value is not None:
            clean_attrs[key] = value
    if kind == "image":
        if "src" not in clean_attrs:
            raise _fail("그림 주소가 없습니다.")
        counter["images"] += 1
    if kind in ("tableHeader", "tableCell"):
        clean_attrs.setdefault("colspan", 1)
        clean_attrs.setdefault("rowspan", 1)
    if clean_attrs:
        out["attrs"] = clean_attrs

    if kind == "text":
        text = node.get("text")
        if not isinstance(text, str) or not text:
            raise _fail("빈 글자 요소입니다.")
        counter["text"] += len(text)
        out["text"] = text
        marks = node.get("marks") or []
        if not isinstance(marks, list):
            raise _fail("서식 목록의 모양이 올바르지 않습니다.")
        clean_marks = [_mark(m) for m in marks]
        if clean_marks:
            out["marks"] = clean_marks
        return out
    if node.get("marks"):
        raise _fail(f"{kind} 에는 서식을 붙일 수 없습니다.")

    content = node.get("content") or []
    if not isinstance(content, list):
        raise _fail("하위 요소 목록의 모양이 올바르지 않습니다.")
    if content and not _CHILDREN[kind]:
        raise _fail(f"{kind} 는 하위 요소를 가질 수 없습니다.")
    if content:
        out["content"] = [_node(c, parent=kind, depth=depth + 1, counter=counter) for c in content]
    return out


def _mark(mark: Any) -> dict[str, Any]:
    if not isinstance(mark, dict) or mark.get("type") not in _MARK_ATTRS:
        kind = mark.get("type") if isinstance(mark, dict) else mark
        raise _fail(f"허용하지 않는 서식입니다: {str(kind)[:40]}")
    kind = mark["type"]
    attrs = mark.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise _fail("서식 속성의 모양이 올바르지 않습니다.")
    allowed = _MARK_ATTRS[kind]
    clean: dict[str, Any] = {}
    for key, value in attrs.items():
        if key not in allowed:
            if value is None:
                continue
            raise _fail(f"{kind} 서식에 허용하지 않는 속성입니다: {str(key)[:40]}")
        if not allowed[key](value):
            raise _fail(f"{kind}.{key} 값이 허용 범위 밖입니다.")
        if kind == "link" and key in _DROP_LINK_ATTRS:
            continue
        if value is not None:
            clean[key] = value.strip() if kind == "link" and key == "href" else value
    if kind == "link" and "href" not in clean:
        raise _fail("링크 주소가 없습니다.")
    out: dict[str, Any] = {"type": kind}
    if clean:
        out["attrs"] = clean
    return out


# --------------------------------------------------------------------------- 텍스트 · 그림

_BLOCK_SEP = "\n"


def to_text(doc: dict[str, Any] | None) -> str:
    """검색 · Excel · RAG · 옛 API 가 읽을 순수 텍스트.

    표는 한 행을 한 줄로, 칸은 ' | ' 로 잇는다 — 검색에 걸리고 Excel 칸에서도 읽힌다.
    그림은 '[그림: 설명]' 으로 자리를 남긴다(무엇이 있었는지 글만 보고도 알 수 있게).
    """
    if not doc:
        return ""
    lines: list[str] = []
    _blocks(doc.get("content") or [], lines, prefix="")
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _inline_text(nodes: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for n in nodes:
        kind = n.get("type")
        if kind == "text":
            out.append(n.get("text", ""))
        elif kind == "hardBreak":
            out.append("\n")
        elif kind == "image":
            out.append(_image_label(n))
    return "".join(out)


def _image_label(node: dict[str, Any]) -> str:
    attrs = node.get("attrs") or {}
    caption = (attrs.get("alt") or attrs.get("title") or "").strip()
    return f"[그림: {caption}]" if caption else "[그림]"


def _blocks(nodes: list[dict[str, Any]], lines: list[str], *, prefix: str) -> None:
    for n in nodes:
        kind = n.get("type")
        content = n.get("content") or []
        if kind in ("paragraph", "heading"):
            lines.append(prefix + _inline_text(content))
        elif kind == "image":
            lines.append(prefix + _image_label(n))
        elif kind == "codeBlock":
            lines.append(_inline_text(content))
        elif kind == "horizontalRule":
            lines.append("")
        elif kind == "blockquote":
            _blocks(content, lines, prefix=prefix + "> ")
        elif kind in ("bulletList", "orderedList", "taskList"):
            start = (n.get("attrs") or {}).get("start") or 1
            for i, item in enumerate(content):
                if kind == "bulletList":
                    mark = "- "
                elif kind == "orderedList":
                    mark = f"{start + i}. "
                else:
                    mark = "[x] " if (item.get("attrs") or {}).get("checked") else "[ ] "
                sub: list[str] = []
                _blocks(item.get("content") or [], sub, prefix="")
                first, *rest = sub or [""]
                lines.append(prefix + mark + first)
                lines.extend(prefix + "  " + line for line in rest)
        elif kind == "table":
            for row in content:
                cells = []
                for cell in row.get("content") or []:
                    sub: list[str] = []
                    _blocks(cell.get("content") or [], sub, prefix="")
                    cells.append(" ".join(s for s in sub if s).strip())
                lines.append(prefix + " | ".join(cells))
        lines_needing_gap = ("table", "codeBlock", "blockquote", "bulletList", "orderedList",
                             "taskList")
        if kind in lines_needing_gap:
            lines.append("")


def image_ids(doc: dict[str, Any] | None) -> list[int]:
    """본문에 들어 있는 그림의 첨부 번호(나온 순서, 중복 제거)."""
    found: list[int] = []
    for node in _walk(doc):
        if node.get("type") == "image":
            m = INLINE_IMAGE_SRC.match((node.get("attrs") or {}).get("src") or "")
            if m and int(m.group(1)) not in found:
                found.append(int(m.group(1)))
    return found


def link_hrefs(doc: dict[str, Any] | None) -> list[str]:
    found: list[str] = []
    for node in _walk(doc):
        for mark in node.get("marks") or []:
            if mark.get("type") == "link":
                href = (mark.get("attrs") or {}).get("href")
                if href and href not in found:
                    found.append(href)
    return found


def _walk(doc: dict[str, Any] | None):
    if not doc:
        return
    stack = [doc]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.get("content") or []))


def media_signature(doc: dict[str, Any] | None) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """재확인 판정에 쓰는 '글 밖의 내용' — 그림과 링크 주소. 크기 · 색은 넣지 않는다."""
    return tuple(image_ids(doc)), tuple(link_hrefs(doc))


def rewrite_images(doc: dict[str, Any], mapping: dict[int, int]) -> dict[str, Any]:
    """그림 번호를 바꾼 사본(다른 글의 그림을 복사해 들여올 때)."""
    if not mapping:
        return doc
    clone = json.loads(json.dumps(doc))
    for node in _walk(clone):
        if node.get("type") == "image":
            attrs = node.get("attrs") or {}
            m = INLINE_IMAGE_SRC.match(attrs.get("src") or "")
            if m and int(m.group(1)) in mapping:
                attrs["src"] = f"/api/v1/attachments/{mapping[int(m.group(1))]}/inline"
    return clone


def summary(doc: dict[str, Any] | None) -> dict[str, int] | None:
    """감사 기록에 남길 요약. 본문 구조 자체는 감사로그에 넣지 않는다."""
    if not doc:
        return None
    nodes = list(_walk(doc))
    return {"nodes": len(nodes),
            "images": len(image_ids(doc)),
            "tables": sum(1 for n in nodes if n.get("type") == "table"),
            "code_blocks": sum(1 for n in nodes if n.get("type") == "codeBlock")}


def from_text(text: str | None) -> dict[str, Any]:
    """서식 없는 옛 글을 문서 구조로 — 줄마다 한 문단. 편집을 시작할 때 쓴다."""
    lines = (text or "").split("\n")
    content = [{"type": "paragraph", "content": [{"type": "text", "text": line}]} if line
               else {"type": "paragraph"} for line in lines]
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}
