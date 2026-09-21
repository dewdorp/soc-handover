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
        ["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log", "csv",
         "xlsx", "xls", "docx", "pptx", "zip", "7z"],
        "attachment", "업로드 허용 확장자", False,
    ),
    "attachment.max_size_mb": (settings.UPLOAD_MAX_MB, "attachment", "파일당 최대 크기(MB)", False),
    "retention.audit_days": (365, "retention",
                             "감사로그 보존일수. 지난 것은 매일 백업 직후 backup/audit-archive 로 옮긴 뒤 DB 에서 지운다(최소 365일).",
                             False),
    "export.max_rows": (settings.EXPORT_MAX_ROWS, "export", "Export 최대 행수", False),
    "shift.carry_forward_auto": (True, "shift", "미완료 업무를 다음 교대 Basket 후보로 자동 제시", False),
    "import.header_aliases": (
        {}, "import",
        "Excel 헤더 별칭 추가분. 한 줄에 '필드: 별칭, 별칭' — 예) content: 조치내역. 코드 기본값과 합쳐진다(D-01).",
        False,
    ),
    "import.status_aliases": (
        {}, "import",
        "Excel 진행상황 문구 → 상태 코드 추가분. 한 줄에 '상태코드: 문구, 문구' — 예) DONE: 처리끝.",
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

    record(db, action=actions.SETTING_CHANGE, ctx=ctx, user=actor, resource_type="SETTING",
           resource_id=key,
           before=None if row.is_secret else {"value": before},
           after=None if row.is_secret else {"value": value})


# --------------------------------------------------------------------------- 관리 화면에서 고치기

#: 올리면 안 되는 확장자 — 허용 목록에 넣으려 해도 거절한다(실행 · 스크립트 · 브라우저가 실행하는 형식).
BLOCKED_EXT = frozenset({
    "exe", "bat", "cmd", "com", "ps1", "psm1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "msi", "msp",
    "dll", "scr", "cpl", "jar", "sh", "hta", "lnk", "reg", "html", "htm", "xhtml", "svg", "php", "asp",
    "aspx", "jsp",
})

#: 화면이 알맞은 입력칸을 그리고, 서버가 저장 전에 검사하는 규칙.
SPEC: dict[str, dict[str, Any]] = {
    "ack.reack_fields": {"kind": "fields", "label": "재확인 필드"},
    "attachment.allowed_ext": {"kind": "ext_list", "label": "첨부 허용 확장자"},
    "attachment.max_size_mb": {"kind": "int", "min": 1, "max": 200, "unit": "MB", "label": "첨부 최대 크기"},
    "retention.audit_days": {"kind": "int", "min": 365, "max": 3650, "unit": "일", "label": "감사로그 보존"},
    "export.max_rows": {"kind": "int", "min": 1_000, "max": 1_000_000, "unit": "행", "label": "Export 최대 행수"},
    "shift.carry_forward_auto": {"kind": "bool", "label": "미완료 자동 이어 넘기기"},
    "import.header_aliases": {"kind": "aliases", "label": "Import 컬럼 별칭"},
    "import.status_aliases": {"kind": "aliases", "label": "Import 상태 별칭"},
}


def spec_for(key: str) -> dict[str, Any] | None:
    spec = SPEC.get(key)
    if spec and spec["kind"] == "fields":
        from app.services.handover_service import FIELD_NAMES
        return {**spec, "choices": [{"value": k, "label": v} for k, v in FIELD_NAMES.items()
                                    if k not in ("is_pinned",)]}
    return spec


def validate(key: str, value: Any) -> Any:
    """저장 전에 형식과 범위를 검사하고 정리한 값을 돌려준다."""
    from app.core.errors import NotFound, ValidationFailed

    spec = spec_for(key)
    if spec is None:
        raise NotFound(f"고칠 수 없는 설정입니다: {key}")
    kind = spec["kind"]
    fail = lambda msg: ValidationFailed(f"{spec['label']}: {msg}", detail={"key": key})  # noqa: E731
    if kind == "bool":
        if not isinstance(value, bool):
            raise fail("켜기/끄기 값이어야 합니다.")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise fail("정수여야 합니다.")
        if not spec["min"] <= value <= spec["max"]:
            raise fail(f"{spec['min']:,} ~ {spec['max']:,}{spec.get('unit', '')} 사이여야 합니다.")
        return value
    if kind == "fields":
        allowed = {c["value"] for c in spec["choices"]}
        if not isinstance(value, list) or not value or any(v not in allowed for v in value):
            raise fail("인수인계 필드 중에서 하나 이상 고르십시오.")
        return list(dict.fromkeys(value))
    if kind == "ext_list":
        if not isinstance(value, list) or not value:
            raise fail("확장자를 하나 이상 넣으십시오.")
        cleaned = []
        for item in value:
            ext = str(item).strip().lower().lstrip(".")
            if not ext.isalnum() or len(ext) > 10:
                raise fail(f"'{item}' 는 확장자 형식이 아닙니다.")
            if ext in BLOCKED_EXT:
                raise fail(f"'{ext}' 는 실행·스크립트 형식이라 허용할 수 없습니다.")
            cleaned.append(ext)
        return sorted(set(cleaned))
    if kind == "aliases":
        if not isinstance(value, dict) or any(
                not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in value.values()):
            raise fail("'이름: [별칭, …]' 형식이어야 합니다.")
        return {str(k): [x.strip() for x in v if x.strip()] for k, v in value.items()}
    raise fail("알 수 없는 형식입니다.")


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
