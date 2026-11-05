"""검색 보강 생성(RAG)을 **나중에** 붙이기 위한 바닥 공사.

여기에는 모델도 벡터 DB 도 없다. 폐쇄망이라 외부 API 를 쓸 수 없고, 어떤 모델을 들일지는
아직 정해지지 않았다. 지금 정해 두어야 할 것은 그 다음에 바꾸기 어려운 두 가지뿐이다.

1) **사례 문서의 모양**(case document)
   업무 하나를 '검색해서 읽을 수 있는 글' 한 덩이로 어떻게 접느냐. 나중에 색인을 다시
   만들더라도 이 모양이 같으면 질의·평가 기준을 다시 쓰지 않아도 된다.

2) **접근 계약**(access contract)
   누가 무엇을 꺼낼 수 있는가. 이게 흐릿한 채로 색인을 만들면, 색인이 권한을 우회하는
   통로가 된다 — 목록에서는 막아 둔 다른 그룹의 업무가 '요약'이라는 이름으로 나온다.

그래서 이 모듈은 **단 하나의 경로**로만 사례를 내보낸다: search_service.iterate().
목록·검색·Excel 이 쓰는 그 함수다. 열람 그룹·삭제 범위가 자동으로 따라붙고, 새 화면을
붙이면서 조건을 빼먹을 수가 없다.

**절대 들어가지 않는 것**(EXCLUDED 참고)
  · 개인 메모(private_notes)      — 공유 문서가 아니다. 본인만 보는 자리다.
  · 장비 비밀번호(credentials)    — 평문이 색인에 닿으면 금고의 뜻이 사라진다.
  · 감사로그                      — 증적이지 지식이 아니다.
  · 첨부 파일의 내용              — 파일 본문 추출은 별도 결정이 필요하다(지금은 이름만).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.models.handover import Handover
from app.models.user import User
from app.search.dsl import SearchRequest

#: 이 판의 사례 문서 모양. 바뀌면 올린다 — 색인을 다시 만들어야 한다는 신호다.
SCHEMA_VERSION = "1.0"

#: 색인에 **절대** 넣지 않는 자료와 그 이유. 화면·문서·시험이 같은 목록을 본다.
EXCLUDED: tuple[dict[str, str], ...] = (
    {"source": "private_notes", "label": "개인 메모",
     "reason": "본인만 보는 자리다. 공유 검색·내보내기에서도 빠져 있다."},
    {"source": "credentials", "label": "장비 비밀번호",
     "reason": "평문이 색인에 닿으면 금고(AES-256-GCM)의 뜻이 사라진다."},
    {"source": "audit_logs", "label": "감사로그",
     "reason": "증적이지 지식이 아니다. 사람 이름과 접속 흔적이 섞인다."},
    {"source": "attachment_content", "label": "첨부 파일 내용",
     "reason": "본문 추출은 별도 결정이 필요하다(지금은 파일 이름만 싣는다)."},
    {"source": "deleted_handovers", "label": "지운 업무",
     "reason": "지운 것이 요약으로 되살아나면 삭제가 삭제가 아니게 된다."},
)

#: 사례 문서의 각 칸이 무엇인지 — 평가·질의를 만드는 사람이 볼 설명.
FIELDS: tuple[dict[str, str], ...] = (
    {"key": "case_id", "type": "string", "note": "handover:{id}. 색인 키이자 원문으로 돌아가는 주소."},
    {"key": "title", "type": "string", "note": "업무 제목."},
    {"key": "body", "type": "string", "note": "내용 + 비고를 이어 붙인 본문."},
    {"key": "company", "type": "string", "note": "관계사 이름."},
    {"key": "status", "type": "string", "note": "상태 이름(신규 · 진행중 · 완료 …)."},
    {"key": "priority", "type": "string", "note": "중요도 이름."},
    {"key": "tags", "type": "string[]", "note": "태그."},
    {"key": "registered_date", "type": "date", "note": "등록일. 기간으로 거를 때 쓴다."},
    {"key": "work_date", "type": "date|null", "note": "수행일."},
    {"key": "people", "type": "string[]", "note": "전달자 · 담당자 · 확인자 이름(계정 id 는 싣지 않는다)."},
    {"key": "attachment_names", "type": "string[]", "note": "첨부 **이름만**. 내용은 넣지 않는다."},
    {"key": "visibility", "type": "string", "note": "GROUPS | ALL."},
    {"key": "group_ids", "type": "int[]", "note": "이 사례를 볼 수 있는 그룹. 색인에 함께 저장해야 한다."},
    {"key": "updated_at", "type": "datetime", "note": "마지막 변경 시각. 재색인 판단에 쓴다."},
    {"key": "version_no", "type": "int", "note": "원문의 버전. 요약이 어느 판을 봤는지 남긴다."},
)

#: 접근 계약 — 검색기를 만드는 쪽이 지켜야 할 규칙. /rag/contract 로도 내려준다.
CONTRACT: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "rules": [
        "색인에는 group_ids 와 visibility 를 **반드시 함께** 저장한다. 질의 시점에 "
        "'그 사람이 지금 속한 그룹'과 맞춰 거르지 않으면, 색인이 권한을 우회하는 통로가 된다.",
        "권한 판정의 기준은 색인이 아니라 DB 다. 검색기는 후보를 추린 뒤 "
        "반드시 원문을 다시 읽어(handover_service.get_or_404) 그 사람이 볼 수 있는지 확인한다.",
        "사람이 그룹에서 빠지면 다음 질의부터 막혀야 한다. 색인을 다시 만들 때까지 "
        "기다리는 구조를 만들지 않는다.",
        "답변에는 근거가 된 case_id 를 함께 낸다. 원문으로 돌아갈 수 없는 요약은 내지 않는다.",
        "EXCLUDED 에 있는 자료는 어떤 경로로도 색인에 넣지 않는다.",
        "외부로 나가는 호출을 두지 않는다(폐쇄망). 모델·색인은 모두 같은 서버 안에 둔다.",
    ],
    "excluded": list(EXCLUDED),
    "fields": list(FIELDS),
    "source_of_truth": "search_service.iterate() — 목록 · 검색 · Excel 과 같은 함수",
}


def _people(db: Session, handover: Handover) -> list[str]:
    """이름만 싣는다 — 계정 id 는 본문에 넣지 않는다(검색 결과에 계정이 섞이지 않게)."""
    names: list[str] = []
    for user_field, raw_field in (("sender", "sender_name_raw"),
                                  ("assignee", "assignee_name_raw"),
                                  ("checker", "checker_name_raw")):
        user = getattr(handover, user_field, None)
        if user is not None:
            names.append(user.display_name)
        raw = getattr(handover, raw_field, None)
        if raw and raw not in names:
            names.append(raw)
    return names


def _attachment_names(db: Session, handover_id: int) -> list[str]:
    from app.services import attachment_service

    return [a.original_name for a in attachment_service.list_for(db, "HANDOVER", handover_id)]


def case_document(db: Session, handover: Handover, *,
                  with_attachments: bool = True) -> dict[str, Any]:
    """업무 하나 → 사례 문서 한 덩이. FIELDS 가 이 함수의 설명서다."""
    from app.services import group_service, handover_service

    body_parts = [handover.content or ""]
    if handover.remark:
        body_parts.append(f"[비고] {handover.remark}")

    return {
        "case_id": f"handover:{handover.id}",
        "handover_id": handover.id,
        "title": handover.title,
        "body": "\n\n".join(p for p in body_parts if p.strip()),
        "company": handover.company.name if handover.company else None,
        "status": handover.status.name if handover.status else handover.status_code,
        "priority": handover.priority.name if handover.priority else handover.priority_code,
        "tags": handover_service.tag_names(handover),
        "registered_date": handover.registered_date,
        "work_date": handover.work_date,
        "people": _people(db, handover),
        "attachment_names": _attachment_names(db, handover.id) if with_attachments else [],
        "visibility": handover.visibility,
        "group_ids": group_service.group_ids_of(handover),
        "updated_at": handover.updated_at,
        "version_no": handover.current_version_no,
        "schema_version": SCHEMA_VERSION,
    }


def iterate_cases(db: Session, actor: User, request: SearchRequest | None = None,
                  *, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """색인을 만들 쪽이 쓰는 유일한 입구.

    search_service.iterate 를 지나므로 **열람 그룹과 삭제 범위가 그대로 적용된다**.
    즉 '색인 작업을 돌린 사람이 볼 수 있는 것'만 나온다 — 그래서 색인은 관리자가 아니라
    전용 계정으로 돌리고, 그 계정이 어느 그룹에 속하는지가 곧 색인의 범위가 된다.
    """
    from app.services import search_service

    req = request or SearchRequest(page=1, size=1)
    req = req.model_copy(update={"include_deleted": False})
    count = 0
    for handover in search_service.iterate(db, req, actor):
        yield case_document(db, handover)
        count += 1
        if limit is not None and count >= limit:
            return


def sample(db: Session, actor: User, *, limit: int = 20) -> dict[str, Any]:
    """검증용 묶음 — 사례 몇 개 + 계약 + '이 범위는 무엇인가'."""
    from app.services import group_service

    cases = list(iterate_cases(db, actor, limit=limit))
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "actor_id": actor.id,
            "group_ids": list(group_service.my_group_ids(db, actor.id)),
            "note": "이 묶음은 요청한 계정이 볼 수 있는 범위다. 색인 범위도 같은 방식으로 정해진다.",
        },
        "count": len(cases),
        "cases": cases,
    }


# --------------------------------------------------------------------------- 검증 예시

#: 붙이는 쪽이 '되는지' 확인할 때 쓰는 질문과, 그때 반드시 지켜져야 할 것.
#: 모델이 없으므로 답을 채점하지 않는다 — **경계가 지켜지는지**만 본다.
VERIFICATION_EXAMPLES: tuple[dict[str, Any], ...] = (
    {
        "id": "scope-other-group",
        "question": "다른 그룹에만 공개된 업무의 제목으로 물어본다",
        "must_hold": "근거 목록에 그 case_id 가 없고, 본문도 인용되지 않는다",
        "why": "색인이 권한을 우회하는 가장 흔한 길",
    },
    {
        "id": "scope-revoked",
        "question": "그룹에서 뺀 직후 같은 질문을 다시 한다",
        "must_hold": "다시 색인하지 않아도 그 순간부터 빠진다",
        "why": "색인 갱신 주기만큼 권한이 늦게 회수되면 회수가 아니다",
    },
    {
        "id": "exclude-private-note",
        "question": "개인 메모에만 적은 문구로 물어본다",
        "must_hold": "아무것도 찾지 못한다",
        "why": "개인 메모는 공유 자리가 아니다",
    },
    {
        "id": "exclude-credential",
        "question": "장비 비밀번호 보관함에 넣은 계정 이름으로 물어본다",
        "must_hold": "비밀번호도, 그 값의 일부도 나오지 않는다",
        "why": "평문이 색인에 닿으면 금고의 뜻이 사라진다",
    },
    {
        "id": "exclude-deleted",
        "question": "지운 업무의 내용으로 물어본다",
        "must_hold": "찾지 못한다",
        "why": "지운 것이 요약으로 되살아나면 삭제가 삭제가 아니다",
    },
    {
        "id": "cite-source",
        "question": "아무 업무나 하나를 요약해 달라고 한다",
        "must_hold": "답에 case_id 가 붙고, 그 주소로 원문이 열린다",
        "why": "근거 없는 요약은 운영에서 쓸 수 없다",
    },
)
