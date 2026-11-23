"""댓글 · 운영 지식 · 할일처럼 '본문 + 서식 구조'를 함께 저장하는 곳의 공통 처리.

인수인계 본문은 버전 · 재확인 판정이 얽혀 handover_service 에 따로 있다. 여기는 그 밖의
본문에 같은 규칙을 적용한다.

  · 서식 구조(doc)를 받으면 허용 목록으로 검사하고, 본문 텍스트는 **서버가 그것에서
    다시 뽑는다**(검색 · 알림 · RAG 가 이 텍스트를 읽는다).
  · 붙여 넣은 그림(초안)은 그 글에 묶는다 — 권한은 그 글을 그대로 따른다.
  · doc 을 보내지 않으면 서식 없는 글이다(옛 화면 · 옛 API).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core import richdoc
from app.core.errors import ValidationFailed
from app.models.user import User
from app.services import attachment_service


def prepare(db: Session, actor: User, *, text: str | None, doc: dict[str, Any] | None,
            entity_type: str, entity_id: int | None,
            max_text: int | None = None) -> tuple[str, dict[str, Any] | None]:
    """(저장할 순수 텍스트, 저장할 구조). entity_id 가 없으면 그림 묶기는 부르는 쪽이 한다."""
    if doc is None:
        return (text or "").strip(), None
    clean = richdoc.validate(doc)
    if entity_id is not None:
        clean = attachment_service.bind_inline(db, actor, clean, entity_type, entity_id)
    plain = richdoc.to_text(clean)
    if max_text is not None and len(plain) > max_text:
        raise ValidationFailed(f"글이 너무 깁니다. {max_text:,}자까지 쓸 수 있습니다.",
                               detail={"field": "doc", "limit_chars": max_text})
    return plain, clean
