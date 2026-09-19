"""내부 알림(FR-I-06). 외부 메일/메신저 없이 화면 안에서만 동작한다.

같은 일로 알림이 계속 쌓이면 아무도 알림을 보지 않게 된다. dedup_key 가 같은
'읽지 않은' 알림이 이미 있으면 새로 만들지 않고 그것을 갱신한다.
(PostgreSQL 에서는 부분 유니크 인덱스 uq_noti_dedup 가 같은 규칙을 DB 에서도 강제한다.)
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.common import Notification

T_TRANSFER = "HANDOVER_TRANSFER"          # 인수인계가 나에게 전달됨
T_REACK = "HANDOVER_REACK"                # 내가 확인한 건의 내용이 바뀜
T_ASSIGNED = "HANDOVER_ASSIGNED"          # 담당자로 지정됨
T_TASK_ASSIGNED = "TASK_ASSIGNED"         # 할일 담당자로 지정됨
T_TASK_COMMENT = "TASK_COMMENT"           # 내 할일에 댓글
T_SCHEDULE_ASSIGNED = "SCHEDULE_ASSIGNED" # 일정 담당자로 지정됨


def notify(db: Session, *, user_id: int, type_: str, title: str, body: str | None = None,
           link_type: str | None = None, link_id: int | None = None,
           dedup_key: str | None = None) -> Notification:
    if dedup_key:
        existing = db.scalar(select(Notification).where(
            Notification.user_id == user_id, Notification.dedup_key == dedup_key,
            Notification.is_read.is_(False)))
        if existing is not None:
            existing.title = title
            existing.body = body
            existing.created_at = now()
            db.flush()
            return existing
    note = Notification(user_id=user_id, type=type_, title=title[:200], body=body,
                        link_type=link_type, link_id=link_id, dedup_key=dedup_key,
                        is_read=False, created_at=now())
    db.add(note)
    db.flush()
    return note


def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.is_read.is_(False))) or 0


def list_for(db: Session, user_id: int, *, unread_only: bool = False,
             limit: int = 50) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(db.scalars(stmt.order_by(Notification.created_at.desc(),
                                         Notification.id.desc()).limit(limit)))


def mark_read(db: Session, user_id: int, notification_id: int) -> bool:
    """내 알림이면 True(이미 읽었어도 — 두 번 눌러도 같은 결과). 남의 것·없는 것은 False."""
    note = db.scalar(select(Notification).where(Notification.id == notification_id,
                                                Notification.user_id == user_id))
    if note is None:
        return False
    if not note.is_read:
        note.is_read, note.read_at = True, now()
        db.flush()
    return True


def mark_all_read(db: Session, user_id: int) -> int:
    result = db.execute(update(Notification)
                        .where(Notification.user_id == user_id,
                               Notification.is_read.is_(False))
                        .values(is_read=True, read_at=now()))
    return result.rowcount
