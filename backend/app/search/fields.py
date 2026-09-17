"""검색 가능한 필드의 화이트리스트 레지스트리.

**이 파일이 SQL Injection 방어의 핵심이다.** 사용자가 보낸 필드명은 여기 등록된 것만
해석되고, 문자열이 SQL 식별자로 흘러가는 경로가 존재하지 않는다. 연산자도 필드 종류별로
제한되므로 "날짜 필드에 contains" 같은 조합 자체가 만들어지지 않는다.

정렬·Facet 가능 여부도 여기서 정한다. 화면이 무엇을 할 수 있는지 서버가 알려주는 셈이라
프론트가 별도로 목록을 하드코딩할 필요가 없다(GET /search/fields).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute

from app.models.handover import Handover
from app.models.reference import HandoverStatus

# --------------------------------------------------------------------------- 연산자

OP_EQ: Final = "eq"
OP_NE: Final = "ne"
OP_IN: Final = "in"
OP_NOT_IN: Final = "not_in"
OP_CONTAINS: Final = "contains"
OP_NOT_CONTAINS: Final = "not_contains"
OP_STARTS_WITH: Final = "starts_with"
OP_ENDS_WITH: Final = "ends_with"
OP_BETWEEN: Final = "between"
OP_GTE: Final = "gte"
OP_LTE: Final = "lte"
OP_IS_NULL: Final = "is_null"
OP_IS_NOT_NULL: Final = "is_not_null"
OP_ANY_OF_TAGS: Final = "any_of_tags"

ALL_OPS: Final[tuple[str, ...]] = (
    OP_EQ, OP_NE, OP_IN, OP_NOT_IN, OP_CONTAINS, OP_NOT_CONTAINS, OP_STARTS_WITH,
    OP_ENDS_WITH, OP_BETWEEN, OP_GTE, OP_LTE, OP_IS_NULL, OP_IS_NOT_NULL, OP_ANY_OF_TAGS,
)

_NULLABLE_OPS = frozenset({OP_IS_NULL, OP_IS_NOT_NULL})
_TEXT_OPS = frozenset({OP_EQ, OP_NE, OP_CONTAINS, OP_NOT_CONTAINS,
                       OP_STARTS_WITH, OP_ENDS_WITH}) | _NULLABLE_OPS
_ENUM_OPS = frozenset({OP_EQ, OP_NE, OP_IN, OP_NOT_IN}) | _NULLABLE_OPS
_NUMERIC_OPS = frozenset({OP_EQ, OP_NE, OP_IN, OP_NOT_IN, OP_BETWEEN,
                          OP_GTE, OP_LTE}) | _NULLABLE_OPS
_BOOL_OPS = frozenset({OP_EQ})
_TAG_OPS = frozenset({OP_ANY_OF_TAGS, OP_IS_NULL, OP_IS_NOT_NULL})

# --------------------------------------------------------------------------- 종류

KIND_TEXT: Final = "text"
KIND_ENUM: Final = "enum"        # 값 목록이 정해진 코드/외래키 → Facet 대상
KIND_INT: Final = "int"
KIND_DATE: Final = "date"
KIND_DATETIME: Final = "datetime"
KIND_BOOL: Final = "bool"
KIND_TAGS: Final = "tags"
KIND_USER_STATE: Final = "user_state"   # 로그인 사용자 기준으로만 뜻이 있는 값

_OPS_BY_KIND: Final[dict[str, frozenset[str]]] = {
    KIND_TEXT: _TEXT_OPS,
    KIND_ENUM: _ENUM_OPS,
    KIND_INT: _NUMERIC_OPS,
    KIND_DATE: _NUMERIC_OPS,
    KIND_DATETIME: _NUMERIC_OPS,
    KIND_BOOL: _BOOL_OPS,
    KIND_TAGS: _TAG_OPS,
    KIND_USER_STATE: _ENUM_OPS,
}


@dataclass(frozen=True, slots=True)
class FieldDef:
    name: str
    label: str
    kind: str
    column: InstrumentedAttribute | None = None
    sortable: bool = False
    facetable: bool = False
    #: 이 필드를 쓰려면 필요한 권한(없으면 누구나)
    requires_permission: str | None = None
    #: Facet 라벨을 만들 때 참조할 기준정보(None 이면 값 자체가 라벨)
    facet_source: str | None = None

    @property
    def ops(self) -> frozenset[str]:
        return _OPS_BY_KIND[self.kind]

    def supports(self, op: str) -> bool:
        return op in self.ops

    def to_public(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "kind": self.kind,
            "ops": sorted(self.ops), "sortable": self.sortable,
            "facetable": self.facetable, "facet_source": self.facet_source,
        }


def _f(*args, **kwargs) -> FieldDef:
    return FieldDef(*args, **kwargs)


HANDOVER_FIELDS: Final[dict[str, FieldDef]] = {f.name: f for f in (
    _f("id", "번호", KIND_INT, Handover.id, sortable=True),
    _f("company_id", "관계사", KIND_ENUM, Handover.company_id,
       sortable=True, facetable=True, facet_source="company"),
    _f("title", "제목", KIND_TEXT, Handover.title, sortable=True),
    _f("content", "내용", KIND_TEXT, Handover.content),
    _f("remark", "비고", KIND_TEXT, Handover.remark),
    _f("status_code", "상태", KIND_ENUM, Handover.status_code,
       sortable=True, facetable=True, facet_source="status"),
    _f("status_category", "상태 구분", KIND_ENUM, None, facetable=False),
    _f("priority_code", "중요도", KIND_ENUM, Handover.priority_code,
       sortable=True, facetable=True, facet_source="priority"),
    _f("registered_date", "등록일", KIND_DATE, Handover.registered_date, sortable=True),
    _f("work_date", "수행일", KIND_DATE, Handover.work_date, sortable=True),
    _f("completed_at", "완료시각", KIND_DATETIME, Handover.completed_at, sortable=True),
    _f("sender_id", "전달자", KIND_ENUM, Handover.sender_id,
       sortable=True, facetable=True, facet_source="user"),
    _f("sender_name_raw", "전달자(원본)", KIND_TEXT, Handover.sender_name_raw),
    _f("assignee_id", "담당자", KIND_ENUM, Handover.assignee_id,
       sortable=True, facetable=True, facet_source="user"),
    _f("assignee_name_raw", "담당자(원본)", KIND_TEXT, Handover.assignee_name_raw),
    _f("checker_id", "확인자", KIND_ENUM, Handover.checker_id,
       sortable=True, facetable=True, facet_source="user"),
    _f("checker_name_raw", "확인자(원본)", KIND_TEXT, Handover.checker_name_raw),
    _f("is_important", "중요", KIND_BOOL, Handover.is_important, sortable=True),
    _f("is_pinned", "상단고정", KIND_BOOL, Handover.is_pinned, sortable=True),
    _f("is_recurring", "반복", KIND_BOOL, Handover.is_recurring),
    _f("ack_state_cache", "확인상태(전체)", KIND_ENUM, Handover.ack_state_cache,
       sortable=True, facetable=True),
    _f("my_ack_state", "내 확인상태", KIND_USER_STATE, None, facetable=True),
    _f("is_starred", "즐겨찾기", KIND_BOOL, None),
    _f("carry_count", "인계 횟수", KIND_INT, Handover.carry_count, sortable=True),
    _f("tags", "태그", KIND_TAGS, None, facetable=True, facet_source="tag"),
    _f("created_at", "등록시각", KIND_DATETIME, Handover.created_at, sortable=True),
    _f("updated_at", "최근수정", KIND_DATETIME, Handover.updated_at, sortable=True),
    _f("is_deleted", "삭제됨", KIND_BOOL, Handover.is_deleted,
       requires_permission="handover:read_deleted"),
)}


def get_field(name: str) -> FieldDef | None:
    return HANDOVER_FIELDS.get(name)


def sortable_fields() -> list[str]:
    return [f.name for f in HANDOVER_FIELDS.values() if f.sortable]


def facetable_fields() -> list[str]:
    return [f.name for f in HANDOVER_FIELDS.values() if f.facetable]


def status_codes_in_category(category: str):
    """상태 구분(OPEN/WAITING/CLOSED)에 속한 상태 코드들. 미완료 판정의 단일 기준."""
    return select(HandoverStatus.code).where(HandoverStatus.category == category)
