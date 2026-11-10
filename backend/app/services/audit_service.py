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
    actions.LOGIN_SUCCESS: "로그인", actions.LOGIN_FAILURE: "로그인 실패", actions.ACCOUNT_LOCKED: "계정 잠금",
    actions.LOGOUT: "로그아웃",
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
    actions.CREDENTIAL_VAULT_UNLOCK: "금고 단기 열람 시작",
    actions.CREDENTIAL_VAULT_DENIED: "금고 인증 실패",
    actions.CREDENTIAL_VAULT_BATCH_REVEAL: "금고 비밀번호 일괄 열람",
    actions.CREDENTIAL_VAULT_EXTEND: "금고 열람 시간 연장",
    actions.CREDENTIAL_VAULT_LOCK: "금고 잠금",
    actions.HANDOVER_PARTICIPANTS: "업무 담당 · 전파 대상 변경",
    actions.HANDOVER_PROPAGATE: "그룹 단위 전파",
    actions.HANDOVER_REQUEST: "분석 의뢰 · 접수 · 회신",
    actions.ROSTER_TEAM_CHANGE: "근무조 편성 변경", actions.ROSTER_OVERRIDE: "근무 변경(대근 · 맞교환)",
    actions.ROSTER_OVERRIDE_CANCEL: "근무 변경 취소",
    actions.GROUP_CREATE: "그룹 만듬", actions.GROUP_UPDATE: "그룹 변경",
    actions.GROUP_MEMBER_CHANGE: "그룹 구성원 변경",
    actions.GROUP_DATA_MOVE: "분류 없는 자료 이관",
    actions.HANDOVER_SCOPE_CHANGE: "공개 범위 변경",
    actions.SCOPE_PUBLIC_MIGRATE: "과거 자료 전체 공개 전환",
    actions.SCOPE_PUBLIC_REVERT: "전체 공개 전환 되돌리기",
    actions.USER_CREATE: "사용자 등록", actions.USER_UPDATE: "사용자 수정", actions.ROLE_CHANGE: "권한 변경",
    actions.SETTING_CHANGE: "설정 변경",
    actions.KNOWLEDGE_CREATE: "운영 지식 등록",
    actions.KNOWLEDGE_UPDATE: "운영 지식 수정",
    actions.KNOWLEDGE_DELETE: "운영 지식 삭제",
    actions.KNOWLEDGE_RESTORE: "운영 지식 복원",
    actions.KNOWLEDGE_LINK: "운영 지식 · 인수인계 연결",
    actions.BACKUP: "백업", actions.RESTORE: "복구", actions.AUDIT_ARCHIVE: "감사로그 보관 정리",
}

#: 평상시 업무에서 수없이 쌓이는 '봤다' 기록. 기본으로 남기지 않고, 조회 화면에서도 숨긴다.
#: 인증 실패 · 권한 변경 · 내보내기 · 비밀번호 열람은 여기에 **넣지 않는다**(§2 보존 대상).
VIEW_ONLY_ACTIONS: frozenset[str] = frozenset({actions.HANDOVER_VIEW})

ACTION_GROUPS: dict[str, list[str]] = {
    "근무표": [actions.ROSTER_TEAM_CHANGE, actions.ROSTER_OVERRIDE,
            actions.ROSTER_OVERRIDE_CANCEL],
    "열람 그룹": [actions.GROUP_CREATE, actions.GROUP_UPDATE,
              actions.GROUP_MEMBER_CHANGE, actions.GROUP_DATA_MOVE,
              actions.HANDOVER_SCOPE_CHANGE],
    "인증": [actions.LOGIN_SUCCESS, actions.LOGIN_FAILURE, actions.ACCOUNT_LOCKED,
           actions.LOGOUT, actions.PASSWORD_CHANGE,
           actions.PASSWORD_RESET],
    "인수인계": [actions.HANDOVER_VIEW, actions.HANDOVER_CREATE, actions.HANDOVER_UPDATE,
             actions.HANDOVER_DELETE, actions.HANDOVER_RESTORE, actions.HANDOVER_UNDELETE,
             actions.HANDOVER_TRANSFER, actions.HANDOVER_ACKNOWLEDGE, actions.HANDOVER_COMMENT,
             actions.HANDOVER_PARTICIPANTS, actions.HANDOVER_PROPAGATE,
             actions.HANDOVER_REQUEST],
    "할일·일정": [actions.TASK_CREATE, actions.TASK_UPDATE, actions.TASK_COMPLETE, actions.TASK_DELETE,
              actions.CALENDAR_CREATE, actions.CALENDAR_UPDATE, actions.CALENDAR_DELETE],
    "데이터 이동": [actions.EXCEL_IMPORT, actions.EXCEL_IMPORT_ROLLBACK, actions.EXCEL_EXPORT,
               actions.ATTACHMENT_UPLOAD, actions.ATTACHMENT_DOWNLOAD, actions.ATTACHMENT_DELETE],
    "비밀번호 보관": [actions.CREDENTIAL_CREATE, actions.CREDENTIAL_UPDATE, actions.CREDENTIAL_DELETE,
                actions.CREDENTIAL_REVEAL, actions.CREDENTIAL_REVEAL_DENIED,
                actions.CREDENTIAL_VAULT_UNLOCK, actions.CREDENTIAL_VAULT_DENIED,
                actions.CREDENTIAL_VAULT_BATCH_REVEAL, actions.CREDENTIAL_VAULT_EXTEND,
                actions.CREDENTIAL_VAULT_LOCK],
    "운영 지식": [actions.KNOWLEDGE_CREATE, actions.KNOWLEDGE_UPDATE, actions.KNOWLEDGE_DELETE,
              actions.KNOWLEDGE_RESTORE, actions.KNOWLEDGE_LINK],
    "관리": [actions.USER_CREATE, actions.USER_UPDATE, actions.ROLE_CHANGE, actions.SETTING_CHANGE,
           actions.SCOPE_PUBLIC_MIGRATE, actions.SCOPE_PUBLIC_REVERT,
           actions.BACKUP, actions.RESTORE, actions.AUDIT_ARCHIVE],
}


#: §2 가 요구한 네 갈래 빠른 보기. 위의 ACTION_GROUPS 는 '어느 기능'인지로 나눈 것이고,
#: 이쪽은 '얼마나 중요한가'로 나눈 것이다. 기본 화면은 '일반 열람'을 빼고 보여 준다.
ACTION_VIEWS: dict[str, list[str]] = {
    "중요 행위": [
        actions.LOGIN_FAILURE, actions.ACCOUNT_LOCKED,
        actions.ROLE_CHANGE, actions.GROUP_MEMBER_CHANGE, actions.HANDOVER_SCOPE_CHANGE,
        actions.SCOPE_PUBLIC_MIGRATE, actions.SCOPE_PUBLIC_REVERT,
        actions.CREDENTIAL_REVEAL, actions.CREDENTIAL_REVEAL_DENIED, actions.CREDENTIAL_DELETE,
        actions.CREDENTIAL_VAULT_UNLOCK, actions.CREDENTIAL_VAULT_DENIED,
        actions.CREDENTIAL_VAULT_BATCH_REVEAL,
        actions.EXCEL_EXPORT, actions.EXCEL_IMPORT, actions.EXCEL_IMPORT_ROLLBACK,
        # 첨부를 내려받은 것은 '자료가 밖으로 나간' 일이다 — 단순 열람으로 묶지 않는다
        actions.ATTACHMENT_DOWNLOAD,
        actions.SETTING_CHANGE, actions.BACKUP, actions.RESTORE, actions.AUDIT_ARCHIVE,
        actions.HANDOVER_DELETE, actions.KNOWLEDGE_DELETE,
    ],
    "인증 · 권한": [
        actions.LOGIN_SUCCESS, actions.LOGIN_FAILURE, actions.LOGOUT, actions.ACCOUNT_LOCKED,
        actions.PASSWORD_CHANGE, actions.PASSWORD_RESET,
        actions.USER_CREATE, actions.USER_UPDATE, actions.ROLE_CHANGE,
        actions.GROUP_CREATE, actions.GROUP_UPDATE, actions.GROUP_MEMBER_CHANGE,
        actions.CREDENTIAL_VAULT_UNLOCK, actions.CREDENTIAL_VAULT_DENIED,
        actions.CREDENTIAL_VAULT_EXTEND, actions.CREDENTIAL_VAULT_LOCK,
    ],
    "데이터 변경": [
        actions.HANDOVER_CREATE, actions.HANDOVER_UPDATE, actions.HANDOVER_DELETE,
        actions.HANDOVER_RESTORE, actions.HANDOVER_UNDELETE, actions.HANDOVER_TRANSFER,
        actions.HANDOVER_ACKNOWLEDGE, actions.HANDOVER_COMMENT,
        actions.HANDOVER_PARTICIPANTS, actions.HANDOVER_PROPAGATE, actions.HANDOVER_REQUEST,
        actions.HANDOVER_SCOPE_CHANGE, actions.SCOPE_PUBLIC_MIGRATE, actions.SCOPE_PUBLIC_REVERT,
        actions.TASK_CREATE, actions.TASK_UPDATE, actions.TASK_COMPLETE, actions.TASK_DELETE,
        actions.CALENDAR_CREATE, actions.CALENDAR_UPDATE, actions.CALENDAR_DELETE,
        actions.KNOWLEDGE_CREATE, actions.KNOWLEDGE_UPDATE, actions.KNOWLEDGE_DELETE,
        actions.KNOWLEDGE_RESTORE, actions.KNOWLEDGE_LINK,
        actions.CREDENTIAL_CREATE, actions.CREDENTIAL_UPDATE, actions.CREDENTIAL_DELETE,
        actions.ATTACHMENT_UPLOAD, actions.ATTACHMENT_DELETE,
        actions.GROUP_DATA_MOVE, actions.ROSTER_TEAM_CHANGE, actions.ROSTER_OVERRIDE,
        actions.ROSTER_OVERRIDE_CANCEL,
    ],
    # 기본으로 기록하지 않는 갈래. 관리자가 'audit.track_handover_views' 를 켜면 쌓인다.
    "일반 열람": [
        actions.HANDOVER_VIEW,
    ],
}


def catalog(db: Session) -> dict[str, Any]:
    resource_types = sorted(t for (t,) in db.execute(
        select(AuditLog.resource_type).where(AuditLog.resource_type.is_not(None)).distinct()) if t)
    return {
        "groups": [{"name": g, "actions": [{"code": a, "label": ACTION_LABELS[a]} for a in codes]}
                   for g, codes in ACTION_GROUPS.items()],
        "views": [{"name": v, "actions": sorted(set(codes))} for v, codes in ACTION_VIEWS.items()],
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
    # 기본 화면은 '단순 열람'을 빼고 보여 준다. 찾는 사람이 열람 기록을 직접 고르면 그대로 보여 준다.
    if getattr(req, "hide_views", False) and not (set(req.actions or ()) & VIEW_ONLY_ACTIONS):
        stmt = stmt.where(AuditLog.action.notin_(sorted(VIEW_ONLY_ACTIONS)))
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
    expires = export_service.register_download(token, path, file_name, actor, written, db=db)
    record(db, action=actions.EXCEL_EXPORT, ctx=ctx, user=actor, resource_type="AUDIT",
           resource_id=f"{written}건",
           detail={"rows": written, "conditions": req.model_dump(mode="json", exclude={"page", "size"})})
    return {"download_token": token, "file_name": file_name, "rows": written, "expires_at": expires}
