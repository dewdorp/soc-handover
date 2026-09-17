"""전문검색 백엔드 인터페이스.

한글 형태소 사전 교체 같은 변경이 이 폴더 밖으로 새어 나가지 않게 격리한다
(ARCHITECTURE.md §5.3). 상위 계층은 조건식과 랭킹식만 받아 쓴다.
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.sql.elements import ColumnElement

#: LIKE 에서 특별한 뜻을 갖는 문자. 사용자가 입력한 %, _ 가 와일드카드로 동작하면
#: "10%" 같은 검색이 전혀 다른 결과를 낸다.
LIKE_ESCAPE = "\\"


def escape_like(term: str) -> str:
    return (term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
                .replace("%", LIKE_ESCAPE + "%")
                .replace("_", LIKE_ESCAPE + "_"))


class SearchBackend(Protocol):
    name: str

    def text_condition(self, q: str) -> ColumnElement[bool]:
        """Global Search(q=) 를 WHERE 조건으로."""
        ...

    def rank_expression(self, q: str) -> ColumnElement | None:
        """관련도 정렬용 식. 지원하지 않으면 None."""
        ...
