"""감사 로그 조회 · 내보내기 (FR-I-02·03, ERD audit_logs, SECURITY §5).

- 조회는 **기간 필수**, 최대 93일 — 500만 행에서 무제한 스캔을 막는다(ERD 규칙).
- ANALYST 는 자기 행위만(audit:read_self), MANAGER+ 는 전체(audit:read_all).
- 감사 로그를 내보내는 것도 감사에 남긴다(EXCEL_EXPORT, resource_type=AUDIT).
- 감사 로그는 여기서 읽기만 한다(UPDATE/DELETE 없음).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import has_permission
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import ValidationFailed
from app.core.time import KST
from app.models.common import AuditLog
from app.models.user import User

MAX_RANGE_DAYS = 93

#: 화면 · 내보내기에 쓰는 이름. 모든 Action 에 이름이 있어야 한다(테스트로 강제).
ACTION_LABELS: dict[str, str] = {
    actions.LOGIN_SUCCESS: "로그인", actions.LOGIN_FAILURE: "로그인 실패", actions.LOGOUT: "로그아웃",
    actions.PASSWORD_CHANGE: "비밀번호 변경", actions.PASSWORD_RESET: "비밀번호 초기화",
    actions.HANDOVER_VIEW: "인수인계 열람", actions.HANDOVER_CREATE: "인수인계 등록",
    actions.HANDOVER_UPDATE: "인수인계 수정", actions.HANDOVER_DELETE: "인수인계 삭제",
    actions.HANDOVER_RESTORE: "인수인계 버전 복원", actions.HANDOVER_UNDELETE: "인수인계 삭제 취소",
    actions.HANDOVER_TRANSFER: "교대 인계", actions.HANDOVER_ACKNOWLEDGE: "인수 확인",
    actions.HANDOVER_COMMENT: "인수인계 댓글",
    actions.TASK_CREATE: "할일 등록", actions.TASK_UPDATE: "할일 수정", actions.TASK_COMPLETE: "할일 완료",
    actions.TASK_DELETE: "할일 삭제",
    actions.CALENDAR_CREATE: "일정 등록", actions.CALENDAR_UPDATE: "일정 수정", actions.CALENDAR_DELETE: "일정 삭제",
    actions.EXCEL_IMPORT: "Excel 가져오기", actions.EXCEL_IMPORT_ROLLBACK: "가져오기 되돌리기",
    actions.EXCEL_EXPORT: "Excel 내보내기",
    actions.ATTACHMENT_UPLOAD: "첨부 올림", actions.ATTACHMENT_DOWNLOAD: "첨부 받음",
    actions.ATTACHMENT_DELETE: "첨부 삭제",
    actions.CREDENTIAL_CREATE: "비밀번호 등록", actions.CREDENTIAL_UPDATE: "비밀번호 수정",
    actions.CREDENTIAL_DELETE: "비밀번호 삭제", actions.CREDENTIAL_REVEAL: "비밀번호 열람",
    actions.CREDENTIAL_REVEAL_DENIED: "비밀번호 열람 거부",
    actions.USER_CREATE: "사용자 등록", actions.USER_UPDATE: "사용자 수정", actions.ROLE_CHANGE: "권한 변경",
    actions.SETTING_CHANGE: "설정 변경",
    actions.BACKUP: "백업", actions.RESTORE: "복구", actions.AUDIT_ARCHIVE: "감사로그 보관 정리",
}

ACTION_GROUPS: dict[str, list[str]] = {
    "인증": [actions.LOGIN_SUCCESS, actions.LOGIN_FAILURE, actions.LOGOUT, actions.PASSWORD_CHANGE,
           actions.PASSWORD_RESET],
    "인수인계": [actions.HANDOVER_VIEW, actions.HANDOVER_CREATE, actions.HANDOVER_UPDATE,
             actions.HANDOVER_DELETE, actions.HANDOVER_RESTORE, actions.HANDOVER_UNDELETE,
             actions.HANDOVER_TRANSFER, actions.HANDOVER_ACKNOWLEDGE, actions.HANDOVER_COMMENT],
    "할일·일정": [actions.TASK_CREATE, actions.TASK_UPDATE, actions.TASK_COMPLETE, actions.TASK_DELETE,
              actions.CALENDAR_CREATE, actions.CALENDAR_UPDATE, actions.CALENDAR_DELETE],
    "데이터 이동": [actions.EXCEL_IMPORT, actions.EXCEL_IMPORT_ROLLBACK, actions.EXCEL_EXPORT,
               actions.ATTACHMENT_UPLOAD, actions.ATTACHMENT_DOWNLOAD, actions.ATTACHMENT_DELETE],
    "비밀번호 보관": [actions.CREDENTIAL_CREATE, actions.CREDENTIAL_UPDATE, actions.CREDENTIAL_DELETE,
                actions.CREDENTIAL_REVEAL, actions.CREDENTIAL_REVEAL_DENIED],
    "관리": [actions.USER_CREATE, actions.USER_UPDATE, actions.ROLE_CHANGE, actions.SETTING_CHANGE,
           actions.BACKUP, actions.RESTORE, actions.AUDIT_ARCHIVE],
}


def catalog(db: Session) -> dict[str, Any]:
    resource_types = sorted(t for (t,) in db.execute(
        select(AuditLog.resource_type).where(AuditLog.resource_type.is_not(None)).distinct()) if t)
    return {
        "groups": [{"name": g, "actions": [{"code": a, "label": ACTION_LABELS[a]} for a in codes]}
                   for g, codes in ACTION_GROUPS.items()],
        "resource_types": resource_types,
        "max_range_days": MAX_RANGE_DAYS,
    }


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=KST) if value.tzinfo is None else value


def _statement(actor: User, req):
    start, end = _aware(req.start), _aware(req.end)
    if end <= start:
        raise ValidationFailed("기간의 끝이 시작보다 늦어야 합니다.")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ValidationFailed(f"한 번에 볼 수 있는 기간은 {MAX_RANGE_DAYS}일까지입니다. 기간을 나눠 보십시오.")
    stmt = select(AuditLog).where(AuditLog.occurred_at >= start, AuditLog.occurred_at < end)
    if not has_permission(actor.role_code, "audit:read_all"):
        stmt = stmt.where(AuditLog.user_id == actor.id)          # 자기 행위만
    elif req.user_id is not None:
        stmt = stmt.where(AuditLog.user_id == req.user_id)
    if req.username:
        stmt = stmt.where(AuditLog.username.icontains(req.username.strip(), autoescape=True))
    if req.actions:
        unknown = sorted(set(req.actions) - set(ACTION_LABELS))
        if unknown:
            raise ValidationFailed(f"알 수 없는 행위입니다: {', '.join(unknown)}")
        stmt = stmt.where(AuditLog.action.in_(req.actions))
    if req.resource_type:
        stmt = stmt.where(AuditLog.resource_type == req.resource_type)
    if req.resource_id:
        stmt = stmt.where(AuditLog.resource_id == req.resource_id.strip())
    if req.client_ip:
        stmt = stmt.where(AuditLog.client_ip.startswith(req.client_ip.strip(), autoescape=True))
    if req.result:
        stmt = stmt.where(AuditLog.result == req.result)
    return stmt


def search(db: Session, actor: User, req) -> tuple[list[AuditLog], int]:
    stmt = _statement(actor, req)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    order = (AuditLog.occurred_at.asc(), AuditLog.id.asc()) if req.order == "asc" \
        else (AuditLog.occurred_at.desc(), AuditLog.id.desc())
    rows = list(db.scalars(stmt.order_by(*order).offset((req.page - 1) * req.size).limit(req.size)))
    return rows, total


def to_out(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id, "occurred_at": row.occurred_at, "user_id": row.user_id, "username": row.username,
        "role_code": row.role_code, "client_ip": row.client_ip, "user_agent": row.user_agent,
        "request_id": row.request_id, "action": row.action,
        "action_label": ACTION_LABELS.get(row.action, row.action),
        "resource_type": row.resource_type, "resource_id": row.resource_id,
        "before_value": row.before_value, "after_value": row.after_value, "result": row.result,
        "error_message": row.error_message, "detail": row.detail,
    }


def _json(value: Any) -> str:
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 32_000 else text[:32_000] + "…"   # 엑셀 한 칸 한도


def export(db: Session, actor: User, req, ctx: RequestContext | None) -> dict[str, Any]:
    """조회 조건 그대로 xlsx 로. 상한은 export.max_rows 설정."""
    from app.services import export_service, settings_service
    from app.services.export_service import safe_cell

    stmt = _statement(actor, req)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    limit = int(settings_service.get_value(db, "export.max_rows") or settings.EXPORT_MAX_ROWS)
    if total > limit:
        raise ValidationFailed(f"조건에 맞는 {total:,}건이 한 번에 내보낼 수 있는 {limit:,}건을 넘습니다. "
                               "기간을 좁혀 나눠 내보내 주십시오.", detail={"total": total, "limit": limit})

    import xlsxwriter

    token = export_service.new_token()
    path = settings.exports_dir / f"{token}.xlsx"
    columns = ["시각", "사용자", "역할", "행위", "행위 코드", "대상", "대상 번호", "결과", "IP",
               "요청 ID", "변경 전", "변경 후", "상세", "오류"]
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_formulas": False,
                                         "strings_to_urls": False})
    ws = wb.add_worksheet("감사로그")
    head = wb.add_format({"bold": True, "bg_color": "#EEF2F7", "border": 1})
    for c, name in enumerate(columns):
        ws.write_string(0, c, name, head)
    ws.freeze_panes(1, 0)
    written = 0
    for row in db.scalars(stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                          .execution_options(yield_per=1000)):
        written += 1
        values = [
            row.occurred_at.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"), row.username or "",
            row.role_code or "", ACTION_LABELS.get(row.action, row.action), row.action,
            row.resource_type or "", row.resource_id or "", row.result, row.client_ip or "",
            row.request_id or "", _json(row.before_value), _json(row.after_value), _json(row.detail),
            row.error_message or "",
        ]
        for c, value in enumerate(values):
            ws.write_string(written, c, safe_cell(value))
    ws.autofilter(0, 0, max(written, 1), len(columns) - 1)
    wb.close()

    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M")
    file_name = f"감사로그_{stamp}.xlsx"
    expires = export_service.register_download(token, path, file_name, actor, written)
    record(db, action=actions.EXCEL_EXPORT, ctx=ctx, user=actor, resource_type="AUDIT",
           resource_id=f"{written}건",
           detail={"rows": written, "conditions": req.model_dump(mode="json", exclude={"page", "size"})})
    return {"download_token": token, "file_name": file_name, "rows": written, "expires_at": expires}
