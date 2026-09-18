"""시스템 설정 조회/변경. 기본값은 코드에, 변경값은 DB에 둔다."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.config import settings
from app.core.context import RequestContext
from app.models.common import SystemSetting

#: (기본값, 카테고리, 설명, 비밀여부)
DEFAULTS: dict[str, tuple[Any, str, str, bool]] = {
    "ack.reack_fields": (
        ["title", "content", "work_date", "status_code", "priority_code", "assignee_id"],
        "handover",
        "이 필드가 변경되면 기존 확인(ack)이 '재확인 필요'로 바뀐다(§33).",
        False,
    ),
    "attachment.allowed_ext": (
        ["png", "jpg", "jpeg", "gif", "pdf", "txt", "log", "csv",
         "xlsx", "xls", "docx", "pptx", "zip", "7z"],
        "attachment", "업로드 허용 확장자", False,
    ),
    "attachment.max_size_mb": (settings.UPLOAD_MAX_MB, "attachment", "파일당 최대 크기(MB)", False),
    "ai.search_enabled": (False, "ai", "AI 자연어 검색 사용", False),
    "ai.embedding_enabled": (False, "ai", "임베딩(Vector) 사용", False),
    "ai.summary_enabled": (False, "ai", "AI 요약 사용", False),
    "ai.tag_suggest_enabled": (False, "ai", "AI 태그 추천 사용", False),
    "retention.audit_days": (365, "retention", "감사로그 보존일수", False),
    "export.max_rows": (settings.EXPORT_MAX_ROWS, "export", "Export 최대 행수", False),
    "shift.carry_forward_auto": (True, "shift", "미완료 업무를 다음 교대 Basket 후보로 자동 제시", False),
    "import.header_aliases": (
        {}, "import",
        "Excel 헤더 별칭 추가분. 예) {\"content\": [\"조치내역\"]}. 코드 기본값과 합쳐진다(D-01).",
        False,
    ),
    "import.status_aliases": (
        {}, "import",
        "Excel 진행상황 문구 → 상태 코드 추가분. 예) {\"DONE\": [\"처리끝\"]}.",
        False,
    ),
}


def get_value(db: Session, key: str) -> Any:
    row = db.get(SystemSetting, key)
    if row is not None:
        return row.value
    default = DEFAULTS.get(key)
    return default[0] if default else None


def set_value(db: Session, key: str, value: Any, *, actor=None,
              ctx: RequestContext | None = None) -> None:
    row = db.get(SystemSetting, key)
    before = row.value if row else get_value(db, key)
    if row is None:
        meta = DEFAULTS.get(key, (None, "general", None, False))
        row = SystemSetting(key=key, value=value, category=meta[1],
                            description=meta[2], is_secret=meta[3])
        db.add(row)
    else:
        row.value = value
    row.updated_by = getattr(actor, "id", None)
    db.flush()

    action = actions.SETTING_CHANGE
    if key.startswith("ai."):
        action = actions.AI_ENABLE if value else actions.AI_DISABLE
    record(db, action=action, ctx=ctx, user=actor, resource_type="SETTING",
           resource_id=key,
           before=None if row.is_secret else {"value": before},
           after=None if row.is_secret else {"value": value})


def ensure_defaults(db: Session) -> int:
    """설치/기동 시 누락된 기본 설정을 채운다."""
    created = 0
    for key, (value, category, desc, secret) in DEFAULTS.items():
        if db.get(SystemSetting, key) is None:
            db.add(SystemSetting(key=key, value=value, category=category,
                                 description=desc, is_secret=secret))
            created += 1
    if created:
        db.flush()
    return created


def ai_flags(db: Session) -> dict[str, bool]:
    """AI 기능 플래그. Provider가 disabled면 개별 토글과 무관하게 전부 꺼진 것으로 본다."""
    provider_on = settings.LLM_PROVIDER != "disabled"
    flags = {
        "search": bool(provider_on and get_value(db, "ai.search_enabled")),
        "embedding": bool(provider_on and get_value(db, "ai.embedding_enabled")),
        "summary": bool(provider_on and get_value(db, "ai.summary_enabled")),
        "tag_suggest": bool(provider_on and get_value(db, "ai.tag_suggest_enabled")),
    }
    flags["provider"] = settings.LLM_PROVIDER
    flags["enabled"] = any(v for k, v in flags.items() if isinstance(v, bool))
    return flags
