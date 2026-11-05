"""Export — 목록 화면과 **같은 DSL** 로 뽑는다(FR-F-07).

  · 행 수가 상한을 넘으면 **조용히 자르지 않고 거부**한다. 잘린 파일을 받은 사람은 그게
    전부인 줄 안다. 그게 누락이다.
  · 셀은 전부 문자열로 쓴다(write_string). '=HYPERLINK(...)' 같은 값이 수식으로 실행되는
    CSV/Excel 수식 주입을 막는다.
  · 파일은 요청한 사람만, 유효시간 안에서만 내려받는다.
"""
from __future__ import annotations

import csv
import json
import re
import secrets
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.core.time import now
from app.models.handover import Handover
from app.models.user import User
from app.services import handover_service, search_service, settings_service

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
#: 이 문자로 시작하는 셀은 Excel 이 수식으로 해석할 수 있다(OWASP CSV Injection).
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _person(user, raw: str | None) -> str:
    return user.display_name if user is not None else (raw or "")


def _date(value) -> str:
    return value.isoformat() if value else ""


def _datetime(value) -> str:
    from app.core.time import to_kst
    return to_kst(value).strftime("%Y-%m-%d %H:%M") if value else ""


#: key → (머리글, 값 추출). 화이트리스트라 요청으로 임의 속성을 꺼낼 수 없다.
COLUMNS: dict[str, tuple[str, Callable[[Handover], Any]]] = {
    "id": ("번호", lambda h: h.id),
    "company": ("관계사", lambda h: h.company.name if h.company else ""),
    "registered_date": ("등록일", lambda h: _date(h.registered_date)),
    "work_date": ("수행일", lambda h: _date(h.work_date)),
    "status": ("상태", lambda h: h.status.name if h.status else h.status_code),
    "priority": ("중요도", lambda h: h.priority.name if h.priority else h.priority_code),
    "title": ("제목", lambda h: h.title),
    "content": ("내용", lambda h: h.content),
    "remark": ("비고", lambda h: h.remark or ""),
    "sender": ("전달자", lambda h: _person(h.sender, h.sender_name_raw)),
    "assignee": ("담당자", lambda h: _person(h.assignee, h.assignee_name_raw)),
    "checker": ("확인자", lambda h: _person(h.checker, h.checker_name_raw)),
    "ack_state": ("확인상태(전체)", lambda h: h.ack_state_cache),
    "tags": ("태그", lambda h: ", ".join(handover_service.tag_names(h))),
    "is_important": ("중요", lambda h: "Y" if h.is_important else ""),
    "is_pinned": ("상단고정", lambda h: "Y" if h.is_pinned else ""),
    "carry_count": ("인계횟수", lambda h: h.carry_count),
    "version": ("버전", lambda h: h.current_version_no),
    "completed_at": ("완료시각", lambda h: _datetime(h.completed_at)),
    "updated_at": ("최근수정", lambda h: _datetime(h.updated_at)),
    "source_file": ("원본파일", lambda h: h.source_file or ""),
    "source_sheet": ("원본시트", lambda h: h.source_sheet or ""),
    "source_row": ("원본행", lambda h: h.source_row or ""),
}

DEFAULT_COLUMNS = ["id", "company", "registered_date", "work_date", "status", "priority",
                   "title", "content", "sender", "assignee", "checker", "ack_state",
                   "remark", "tags", "updated_at"]


def safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_LEAD):
        return "'" + text
    return text


def _max_rows(db: Session) -> int:
    return int(settings_service.get_value(db, "export.max_rows") or settings.EXPORT_MAX_ROWS)


def export(db: Session, request, actor: User, ctx: RequestContext) -> dict[str, Any]:
    columns = request.columns or DEFAULT_COLUMNS
    unknown = [c for c in columns if c not in COLUMNS]
    if unknown:
        raise ValidationFailed("내보낼 수 없는 컬럼입니다.",
                               detail={"columns": unknown, "allowed": list(COLUMNS)})

    total = search_service.count_only(db, request, actor)
    limit = _max_rows(db)
    if total > limit:
        raise ValidationFailed(
            f"조건에 맞는 {total:,}건이 한 번에 내보낼 수 있는 {limit:,}건을 넘습니다. "
            "기간 등으로 조건을 좁혀 나눠 내보내 주십시오.",
            detail={"total": total, "limit": limit})

    _purge_expired()
    token = secrets.token_urlsafe(24)
    stamp = now()
    base = f"인수인계_{stamp.strftime('%Y%m%d_%H%M')}"
    rows_iter = search_service.iterate(db, request, actor)

    if request.format == "csv":
        path = settings.exports_dir / f"{token}.csv"
        written = _write_csv(path, columns, rows_iter)
        file_name = f"{base}.csv"
    else:
        path = settings.exports_dir / f"{token}.xlsx"
        written = _write_xlsx(path, columns, rows_iter, request)
        file_name = f"{base}.xlsx"

    expires = register_download(token, path, file_name, actor, written, db=db)

    # 어떤 조건으로 몇 건을 가져갔는지가 감사의 핵심이다(UI_STRUCTURE §8 예시).
    record(db, action=actions.EXCEL_EXPORT, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=f"{written}건",
           detail={"format": request.format, "rows": written, "columns": columns,
                   "dsl": request.model_dump(exclude={"columns", "format", "page", "size"})})
    return {"download_token": token, "file_name": file_name, "rows": written,
            "expires_at": expires}


def _write_xlsx(path: Path, columns: list[str], rows, request) -> int:
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True,
                                         "strings_to_formulas": False,
                                         "strings_to_urls": False,
                                         "strings_to_numbers": False})
    ws = wb.add_worksheet("인수인계")
    head = wb.add_format({"bold": True, "bg_color": "#EEF2F7", "border": 1})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    for c, key in enumerate(columns):
        ws.write_string(0, c, COLUMNS[key][0], head)
        ws.set_column(c, c, 60 if key in ("content", "remark") else 14,
                      wrap if key in ("content", "remark") else None)
    ws.freeze_panes(1, 0)

    r = 1
    for handover in rows:
        for c, key in enumerate(columns):
            value = COLUMNS[key][1](handover)
            if isinstance(value, int) and not isinstance(value, bool):
                ws.write_number(r, c, value)
            else:
                ws.write_string(r, c, "" if value is None else str(value))
        r += 1
    if r > 1:
        ws.autofilter(0, 0, r - 1, len(columns) - 1)

    # 무엇을 기준으로 뽑았는지 파일 안에도 남긴다. 파일만 따로 돌아다녀도 조건을 알 수 있다.
    info = wb.add_worksheet("조건")
    info.write_string(0, 0, "생성시각")
    info.write_string(0, 1, now().strftime("%Y-%m-%d %H:%M:%S"))
    info.write_string(1, 0, "건수")
    info.write_number(1, 1, r - 1)
    info.write_string(2, 0, "조건(DSL)")
    info.write_string(2, 1, json.dumps(
        request.model_dump(exclude={"columns", "format", "page", "size"}),
        ensure_ascii=False, default=str))
    wb.close()
    return r - 1


def _write_csv(path: Path, columns: list[str], rows) -> int:
    # utf-8-sig: Excel 에서 열었을 때 한글이 깨지지 않게 BOM 을 붙인다.
    written = 0
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([COLUMNS[k][0] for k in columns])
        for handover in rows:
            writer.writerow([safe_cell(COLUMNS[k][1](handover)) for k in columns])
            written += 1
    return written


def new_token() -> str:
    _purge_expired()
    return secrets.token_urlsafe(24)


def register_download(token: str, path: Path, file_name: str, actor: User, rows: int,
                      *, db=None):
    """만든 파일을 요청자 본인만 · 유효시간 안에서만 받을 수 있게 등록한다. 만료 시각을 돌려준다.

    만들 때의 **소속 그룹**도 함께 적는다. 파일은 그 순간 볼 수 있던 행들의 사본이므로,
    그 뒤에 그룹에서 빠진 사람이 링크만 눌러 내용을 꺼내 가면 권한 회수가 무의미해진다.
    받을 때 지금 소속과 비교해 좁아졌으면 거절한다(§3 '이미 발급된 토큰도 다음 요청부터 막는다').
    """
    expires = now() + timedelta(minutes=settings.EXPORT_TTL_MINUTES)
    groups: list[int] | None = None
    if db is not None:
        from app.services import group_service
        groups = list(group_service.my_group_ids(db, actor.id))
    _meta_path(token).write_text(json.dumps({
        "owner": actor.id, "file": path.name, "name": file_name,
        "expires": expires.isoformat(), "rows": rows, "groups": groups,
    }, ensure_ascii=False), encoding="utf-8")
    return expires


def _meta_path(token: str) -> Path:
    return settings.exports_dir / f"{token}.json"


def resolve_download(token: str, actor: User, db=None) -> tuple[Path, str]:
    """요청자 본인 · 유효시간 안에서만. 그 밖은 존재 자체를 드러내지 않는다(404)."""
    if not _TOKEN.match(token):
        raise NotFound("내려받을 파일을 찾을 수 없습니다.")
    meta_path = _meta_path(token)
    if not meta_path.exists():
        raise NotFound("내려받을 파일을 찾을 수 없습니다.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    from datetime import datetime
    if meta.get("owner") != actor.id or datetime.fromisoformat(meta["expires"]) < now():
        raise NotFound("내려받을 파일을 찾을 수 없거나 유효시간이 지났습니다.")
    issued = meta.get("groups")
    if db is not None and issued is not None:
        from app.services import group_service
        if set(issued) - set(group_service.my_group_ids(db, actor.id)):
            # 만들 때보다 소속이 좁아졌다 — 파일 안에 지금은 못 보는 행이 있을 수 있다.
            raise NotFound("내려받을 파일을 찾을 수 없습니다. "
                           "열람 그룹이 바뀌었으므로 다시 내보내십시오.")
    path = settings.exports_dir / meta["file"]
    if not path.exists():
        raise NotFound("내려받을 파일을 찾을 수 없습니다.")
    return path, meta["name"]


def _purge_expired() -> None:
    from datetime import datetime
    for meta_path in settings.exports_dir.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if datetime.fromisoformat(meta["expires"]) < now():
                (settings.exports_dir / meta["file"]).unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            continue
