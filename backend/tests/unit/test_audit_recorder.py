"""감사 기록기 단위 테스트 — 특히 비밀값 마스킹."""
from __future__ import annotations

from sqlalchemy import select

from app.audit import actions
from app.audit.recorder import record
from app.models.common import AuditLog


def test_record_masks_secrets(db):
    record(db, action=actions.SETTING_CHANGE, username="admin", role_code="ADMIN",
           resource_type="SETTING", resource_id="llm.api_key",
           before={"api_key": "old-secret", "note": "ok"},
           after={"api_key": "new-secret", "nested": {"password": "p@ss", "keep": 1}})
    db.commit()

    row = db.scalar(select(AuditLog).where(AuditLog.action == actions.SETTING_CHANGE))
    assert row is not None
    assert row.before_value["api_key"] == "***"
    assert row.before_value["note"] == "ok"
    assert row.after_value["api_key"] == "***"
    assert row.after_value["nested"]["password"] == "***"
    assert row.after_value["nested"]["keep"] == 1


def test_record_truncates_long_text(db):
    long_text = "가" * 5000
    record(db, action=actions.HANDOVER_UPDATE, username="hong", role_code="ANALYST",
           resource_type="HANDOVER", resource_id=1, after={"content": long_text})
    db.commit()
    row = db.scalar(select(AuditLog).where(AuditLog.action == actions.HANDOVER_UPDATE))
    assert len(row.after_value["content"]) < 5000
    assert "총 5000자" in row.after_value["content"]


def test_all_required_actions_defined():
    """사양서 §60 이 요구한 이벤트가 모두 정의되어 있어야 한다."""
    required = [
        "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT",
        "HANDOVER_VIEW", "HANDOVER_CREATE", "HANDOVER_UPDATE", "HANDOVER_DELETE",
        "HANDOVER_RESTORE", "HANDOVER_TRANSFER", "HANDOVER_ACKNOWLEDGE",
        "TASK_CREATE", "TASK_UPDATE", "TASK_COMPLETE",
        "CALENDAR_CREATE", "CALENDAR_UPDATE",
        "EXCEL_IMPORT", "EXCEL_EXPORT",
        "USER_CREATE", "USER_UPDATE", "ROLE_CHANGE",
        "SETTING_CHANGE", "BACKUP", "RESTORE",
    ]
    for name in required:
        assert getattr(actions, name, None) == name, f"{name} 액션이 정의되지 않았습니다"


def test_critical_actions_include_high_risk():
    assert actions.ROLE_CHANGE in actions.CRITICAL_ACTIONS
    assert actions.HANDOVER_DELETE in actions.CRITICAL_ACTIONS
    assert actions.RESTORE in actions.CRITICAL_ACTIONS
    assert actions.HANDOVER_VIEW not in actions.CRITICAL_ACTIONS
