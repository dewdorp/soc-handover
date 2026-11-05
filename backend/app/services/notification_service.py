"""내부 알림(FR-I-06). 외부 메일/메신저 없이 화면 안에서만 동작한다.

같은 일로 알림이 계속 쌓이면 아무도 알림을 보지 않게 된다. dedup_key 가 같은
'읽지 않은' 알림이 이미 있으면 새로 만들지 않고 그것을 갱신한다.
(PostgreSQL 에서는 부분 유니크 인덱스 uq_noti_dedup 가 같은 규칙을 DB 에서도 강제한다.)
"""
from __future__ import annotations

from sqlalchemy import false, func, select, update
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.common import Notification

T_TRANSFER = "HANDOVER_TRANSFER"          # 인수인계가 나에게 전달됨
T_REACK = "HANDOVER_REACK"                # 내가 확인한 건의 내용이 바뀜
T_ASSIGNED = "HANDOVER_ASSIGNED"          # 담당자로 지정됨
T_TASK_ASSIGNED = "TASK_ASSIGNED"         # 할일 담당자로 지정됨
T_TASK_COMMENT = "TASK_COMMENT"           # 내 할일에 댓글
T_SCHEDULE_ASSIGNED = "SCHEDULE_ASSIGNED" # 일정 담당자로 지정됨
T_IMPORTANT = "IMPORTANT_HANDOVER"        # 중요 · 긴급 인수인계(관리자에게)
T_TASK_DUE_SOON = "TASK_DUE_SOON"         # 내 할일 마감이 오늘·내일
T_TASK_OVERDUE = "TASK_OVERDUE"           # 내 할일 마감이 지남
T_SHIFT_CHANGE = "SHIFT_CHANGE"           # 내 근무가 바뀜(대근 · 맞교환 · 취소)
T_SCHEDULE_REMINDER = "SCHEDULE_REMINDER"  # 내가 설정한 일정 알림


def notify(db: Session, *, user_id: int, type_: str, title: str, body: str | None = None,
           link_type: str | None = None, link_id: int | None = None,
           dedup_key: str | None = None) -> Notification:
    if dedup_key:
        existing = db.scalar(select(Notification).where(
            Notification.user_id == user_id, Notification.dedup_key == dedup_key,
            Notification.is_read == false()))
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


def notify_once(db: Session, *, user_id: int, dedup_key: str, **kwargs) -> Notification | None:
    """같은 키로 **한 번이라도** 보낸 적이 있으면(읽었어도) 다시 보내지 않는다 — 주기 알림용.
    notify() 는 읽지 않은 것만 갱신하므로, 읽은 뒤 30분마다 같은 알림이 다시 쌓인다."""
    sent = db.scalar(select(Notification.id).where(Notification.user_id == user_id,
                                                   Notification.dedup_key == dedup_key).limit(1))
    if sent is not None:
        return None
    return notify(db, user_id=user_id, dedup_key=dedup_key, **kwargs)


def _readable(db: Session, user_id: int):
    """업무를 가리키는 알림 중 **지금 볼 수 없는 것**을 걸러 내는 조건.

    만들 때 걸러도 소용없다 — 그룹에서 빠지는 일은 알림이 만들어진 뒤에 일어난다.
    그래서 읽을 때마다 판정한다. 그룹이 바뀌면 다음 요청부터 제목이 사라진다.
    """
    from sqlalchemy import and_, exists, or_

    from app.models.handover import Handover
    from app.services import group_service

    visible = exists(select(Handover.id).where(
        Handover.id == Notification.link_id,
        group_service.visible_clause(db, user_id)).correlate(Notification))
    return or_(Notification.link_type != "HANDOVER", Notification.link_type.is_(None),
               and_(Notification.link_type == "HANDOVER", visible))


def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.is_read == false(),
        _readable(db, user_id))) or 0


def list_for(db: Session, user_id: int, *, unread_only: bool = False,
             limit: int = 50) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id,
                                      _readable(db, user_id))
    if unread_only:
        stmt = stmt.where(Notification.is_read == false())
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
                               Notification.is_read == false())
                        .values(is_read=True, read_at=now()))
    return result.rowcount
