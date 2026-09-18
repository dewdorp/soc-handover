"""헤더 · 상태값 별칭 사전 (ASSUMPTIONS D-01).

실제 Excel 을 아직 보지 못했으므로 §45 의 8개 컬럼을 기준으로 흔한 변형을 흡수한다.
사전은 **코드 수정 없이 설정으로 늘릴 수 있다** — system_settings 의
`import.header_aliases` / `import.status_aliases` 에 추가하면 여기 기본값과 합쳐진다.
"""
from __future__ import annotations

from typing import Final

from sqlalchemy.orm import Session

from app.utils.fingerprint import norm

# --------------------------------------------------------------------------- 시스템 필드

F_COMPANY: Final = "company"
F_REGISTERED: Final = "registered_date"
F_WORK: Final = "work_date"
F_STATUS: Final = "status"
F_CONTENT: Final = "content"
F_TITLE: Final = "title"
F_SENDER: Final = "sender"
F_CHECKER: Final = "checker"
F_ASSIGNEE: Final = "assignee"
F_SENDER_CHECKER: Final = "sender_checker"   # '전달자/확인자' 처럼 한 칸에 둘이 든 경우
F_REMARK: Final = "remark"
F_PRIORITY: Final = "priority"

#: 화면 드롭다운에 보이는 순서와 이름
TARGETS: Final[list[tuple[str, str]]] = [
    (F_COMPANY, "관계사"),
    (F_REGISTERED, "등록일"),
    (F_WORK, "수행일"),
    (F_STATUS, "상태"),
    (F_TITLE, "제목"),
    (F_CONTENT, "내용"),
    (F_SENDER, "전달자"),
    (F_CHECKER, "확인자"),
    (F_SENDER_CHECKER, "전달자/확인자"),
    (F_ASSIGNEE, "담당자"),
    (F_PRIORITY, "중요도"),
    (F_REMARK, "비고"),
]
TARGET_NAMES: Final = frozenset(t for t, _ in TARGETS)

HEADER_ALIASES: Final[dict[str, list[str]]] = {
    F_COMPANY: ["관계사", "고객사", "회사", "회사명", "관계사명", "업체", "업체명", "기관", "고객"],
    F_REGISTERED: ["날짜", "일자", "등록일", "등록일자", "작성일", "작성일자", "접수일", "일시"],
    F_WORK: ["수행날짜", "수행일", "수행일자", "수행예정일", "조치일", "조치일자",
             "처리일", "작업일", "예정일"],
    F_STATUS: ["진행상황", "진행 상황", "상태", "진행상태", "처리상태", "처리현황", "결과"],
    F_TITLE: ["제목", "건명", "요약", "항목"],
    F_CONTENT: ["내용", "인수인계내용", "인수인계 내용", "상세", "상세내용", "세부내용",
                "업무내용", "전달사항", "인계내용"],
    F_SENDER: ["전달자", "인계자", "작성자", "보고자", "등록자"],
    F_CHECKER: ["확인자", "인수자", "수신자", "검토자"],
    F_SENDER_CHECKER: ["전달자/확인자", "전달자 / 확인자", "인계자/인수자", "전달/확인"],
    F_ASSIGNEE: ["담당자", "담당", "처리자", "조치자", "수행자"],
    F_PRIORITY: ["중요도", "우선순위", "긴급도", "등급"],
    F_REMARK: ["비고", "메모", "참고", "특이사항", "기타"],
}

#: 엑셀에 적힌 진행상황 문구 → 상태 코드. 관리자가 만든 상태의 '이름'도 자동으로 매칭된다.
STATUS_ALIASES: Final[dict[str, list[str]]] = {
    "DONE": ["완료", "처리완료", "조치완료", "종료", "해결", "완", "done", "closed", "end"],
    "IN_PROGRESS": ["진행", "진행중", "처리중", "조치중", "작업중", "ing", "진행 중"],
    "NEED_CHECK": ["확인필요", "확인 필요", "확인요망", "검토필요", "확인요청"],
    "ACTION_PLANNED": ["조치예정", "예정", "작업예정", "처리예정"],
    "WAITING": ["대기", "회신대기", "답변대기", "승인대기"],
    "HOLD": ["보류", "중단"],
    "CANCELED": ["취소", "철회", "무효"],
    "NEW": ["신규", "접수", "등록"],
}

PRIORITY_ALIASES: Final[dict[str, list[str]]] = {
    "URGENT": ["긴급", "최우선", "urgent", "critical", "상"],
    "HIGH": ["높음", "중요", "high"],
    "NORMAL": ["보통", "일반", "normal", "중"],
    "LOW": ["낮음", "low", "하"],
}


def _merged(base: dict[str, list[str]], extra: object) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in base.items()}
    if isinstance(extra, dict):
        for key, values in extra.items():
            if isinstance(values, list):
                out.setdefault(str(key), []).extend(str(v) for v in values)
    return out


def header_aliases(db: Session | None = None) -> dict[str, list[str]]:
    if db is None:
        return HEADER_ALIASES
    from app.services import settings_service
    return _merged(HEADER_ALIASES, settings_service.get_value(db, "import.header_aliases"))


def status_aliases(db: Session | None = None) -> dict[str, list[str]]:
    if db is None:
        return STATUS_ALIASES
    from app.services import settings_service
    return _merged(STATUS_ALIASES, settings_service.get_value(db, "import.status_aliases"))


def build_lookup(aliases: dict[str, list[str]]) -> dict[str, str]:
    """정규화된 별칭 → 대상. '진행 상황', '진행상황', '진행-상황' 을 같은 것으로 본다."""
    table: dict[str, str] = {}
    for target, words in aliases.items():
        table.setdefault(norm(target), target)
        for word in words:
            table.setdefault(norm(word), target)
    return table
