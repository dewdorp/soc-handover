"""Quick Filter 프리셋 (FR-A-10).

버튼 하나가 곧 DSL 조각이다. 서버가 정의를 갖고 있으므로 화면·Export·AI 가 같은 뜻으로
동작하고, "미완료"의 의미가 화면마다 달라지는 사고를 막는다.

미완료 판정은 상태 코드를 나열하지 않고 반드시 `handover_statuses.category` 를 쓴다
(ASSUMPTIONS B-04 단일 기준). 관리자가 상태를 추가해도 자동으로 따라온다.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Final

from app.core.time import today
from app.models.handover import ACK_PENDING, ACK_REACK
from app.search.dsl import Filter

CAT_OPEN: Final = "OPEN"
CAT_WAITING: Final = "WAITING"
CAT_CLOSED: Final = "CLOSED"


def _today(_: int) -> list[Filter]:
    return [Filter(field="registered_date", op="between", value="TODAY")]


def _mine(user_id: int) -> list[Filter]:
    return [Filter(field="assignee_id", op="eq", value=user_id)]


def _in_progress(_: int) -> list[Filter]:
    return [Filter(field="status_code", op="eq", value="IN_PROGRESS")]


def _open(_: int) -> list[Filter]:
    """미완료 = 완료도 취소도 아닌 것. 카테고리 기준."""
    return [Filter(field="status_category", op="in", value=[CAT_OPEN, CAT_WAITING])]


def _need_ack(_: int) -> list[Filter]:
    return [Filter(field="my_ack_state", op="in", value=[ACK_PENDING, ACK_REACK])]


def _important(_: int) -> list[Filter]:
    return [Filter(field="is_important", op="eq", value=True)]


def _overdue(_: int) -> list[Filter]:
    """지연 = 수행일이 이미 지났는데 아직 끝나지 않은 것."""
    yesterday = today() - timedelta(days=1)
    return [
        Filter(field="work_date", op="lte", value=yesterday.isoformat()),
        Filter(field="status_category", op="in", value=[CAT_OPEN, CAT_WAITING]),
    ]


QUICK_FILTERS: Final[dict[str, tuple[str, Callable[[int], list[Filter]]]]] = {
    "TODAY": ("오늘", _today),
    "MINE": ("내 담당", _mine),
    "IN_PROGRESS": ("진행중", _in_progress),
    "OPEN": ("미완료", _open),
    "NEED_ACK": ("확인필요", _need_ack),
    "IMPORTANT": ("중요", _important),
    "OVERDUE": ("지연", _overdue),
}


def expand(tokens: list[str], user_id: int) -> list[Filter]:
    """Quick Filter 토큰들을 DSL 필터로 펼친다. 여러 개를 켜면 AND 다."""
    out: list[Filter] = []
    for token in tokens:
        entry = QUICK_FILTERS.get(token.upper())
        if entry is not None:
            out.extend(entry[1](user_id))
    return out


def catalog() -> list[dict]:
    """화면 버튼 구성을 위한 목록."""
    return [{"token": token, "label": label} for token, (label, _) in QUICK_FILTERS.items()]
