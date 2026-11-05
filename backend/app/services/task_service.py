"""할일(Task) 규칙 — 생성 · 수정 · 보드 이동 · 체크리스트 · 댓글 · 인수인계에서 바로 만들기 (FR-D).

- 할일은 인수인계(사실 기록)와 분리된 '해야 할 일'이다(§37). 인수인계에 연결할 수 있지만
  할일을 바꿔도 인수인계는 바뀌지 않는다.
- 수정·보드 이동은 expected_version 이 맞아야 저장된다(§26). 조용히 덮어쓰지 않는다.
- 권한: 만든 사람·담당자, 또는 task:update_any(관리자). 삭제는 만든 사람(task:delete_own)
  또는 task:delete_any. 삭제는 표시만 한다.
- 감사: 생성·수정·완료·삭제. 보드 이동은 **상태가 바뀔 때만** 남긴다 — 같은 칸 안에서
  순서만 바꾸는 것은 업무 이력이 아니다(ASSUMPTIONS B-11).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import has_permission
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.core.time import KST, now, today, week_start
from app.models.handover import Handover
from app.models.reference import Company, Priority
from app.models.task import (TASK_CLOSED_STATES, TASK_DONE, TASK_IN_PROGRESS, TASK_TODO,
                             TASK_WAITING, Task, TaskChecklist, TaskComment)
from app.models.user import User
from app.services import notification_service

BOARD_COLUMNS = (TASK_TODO, TASK_IN_PROGRESS, TASK_WAITING, TASK_DONE)
#: 보드의 완료 칸은 최근 것만 — 끝난 일이 쌓여 보드를 덮지 않게.
DONE_WINDOW_DAYS = 14
TRACKED = ("title", "description", "status", "priority_code", "assignee_id", "company_id",
           "start_date", "due_date")
EXCERPT = 500


# --------------------------------------------------------------------------- 권한 · 조회

def can_edit(actor: User, task: Task) -> bool:
    if has_permission(actor.role_code, "task:update_any"):
        return True
    if not has_permission(actor.role_code, "task:update"):
        return False
    return actor.id in {task.creator_id, task.assignee_id}


def can_delete(actor: User, task: Task) -> bool:
    if has_permission(actor.role_code, "task:delete_any"):
        return True
    return has_permission(actor.role_code, "task:delete_own") and actor.id == task.creator_id


def get_or_404(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.is_deleted:
        raise NotFound("할일을 찾을 수 없습니다.")
    return task


def _require_edit(actor: User, task: Task) -> None:
    if not can_edit(actor, task):
        raise Forbidden("본인이 만들었거나 담당인 할일만 수정할 수 있습니다.")


def is_overdue(task: Task, on: date | None = None) -> bool:
    return (task.due_date is not None and task.due_date < (on or today())
            and task.status not in TASK_CLOSED_STATES)


def _check_refs(db: Session, *, priority_code: str | None = None, assignee_id: int | None = None,
                company_id: int | None = None, handover_id: int | None = None,
                actor: User | None = None) -> None:
    if priority_code is not None and db.get(Priority, priority_code) is None:
        raise ValidationFailed(f"없는 중요도입니다: {priority_code}")
    if assignee_id is not None:
        user = db.get(User, assignee_id)
        if user is None or not user.is_active:
            raise ValidationFailed("담당자를 찾을 수 없거나 비활성 계정입니다.")
    if company_id is not None and db.get(Company, company_id) is None:
        raise ValidationFailed("관계사를 찾을 수 없습니다.")
    if handover_id is not None:
        handover = db.get(Handover, handover_id)
        if handover is None or handover.is_deleted:
            raise ValidationFailed("연결할 인수인계를 찾을 수 없습니다.")
        # 볼 수 없는 업무에 할일을 매달아 제목·관계사를 끌어오는 길을 막는다.
        if actor is not None:
            from app.services import group_service
            if not group_service.can_see(db, handover, actor):
                raise ValidationFailed("연결할 인수인계를 찾을 수 없습니다.")


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _snapshot(task: Task) -> dict[str, Any]:
    return {k: _jsonable(getattr(task, k)) for k in TRACKED}


def _check_version(task: Task, expected: int) -> None:
    if task.version_no != expected:
        raise VersionConflict(
            "다른 사용자가 이 할일을 먼저 수정했습니다. 최신 내용을 확인한 뒤 다시 시도하십시오.",
            detail={"expected_version": expected, "current_version_no": task.version_no,
                    "current": _snapshot(task)})


def _set_status(task: Task, status: str) -> None:
    if status == task.status:
        return
    task.status = status
    task.completed_at = now() if status == TASK_DONE else None


def _bottom_of(db: Session, status: str) -> int:
    top = db.scalar(select(func.max(Task.board_order))
                    .where(Task.status == status, Task.is_deleted == false()))
    return (top if top is not None else -1) + 1


def _notify_assignee(db: Session, task: Task, actor: User) -> None:
    if task.assignee_id and task.assignee_id != actor.id:
        due = task.due_date.isoformat() if task.due_date else "없음"
        notification_service.notify(
            db, user_id=task.assignee_id, type_=notification_service.T_TASK_ASSIGNED,
            title=f"할일이 배정되었습니다: {task.title}",
            body=f"{actor.display_name} 님이 배정 · 마감 {due}",
            link_type="TASK", link_id=task.id, dedup_key=f"task-assign:{task.id}")


# --------------------------------------------------------------------------- 생성 · 수정

def create(db: Session, actor: User, data: dict[str, Any],
           ctx: RequestContext | None = None) -> Task:
    data = dict(data)
    checklist = [t.strip() for t in (data.pop("checklist", None) or []) if t and t.strip()]
    data["assignee_id"] = data.get("assignee_id") or actor.id
    _check_refs(db, priority_code=data.get("priority_code"), assignee_id=data["assignee_id"],
                company_id=data.get("company_id"), handover_id=data.get("handover_id"),
                actor=actor)
    if data.get("handover_id") and not data.get("company_id"):
        data["company_id"] = db.get(Handover, data["handover_id"]).company_id

    task = Task(**data, creator_id=actor.id, version_no=1)
    task.board_order = _bottom_of(db, task.status)
    if task.status == TASK_DONE:
        task.completed_at = now()
    db.add(task)
    db.flush()
    for order, title in enumerate(checklist):
        db.add(TaskChecklist(task_id=task.id, title=title[:200], sort_order=order))
    db.flush()
    db.refresh(task)

    _notify_assignee(db, task, actor)
    record(db, action=actions.TASK_CREATE, ctx=ctx, user=actor, resource_type="TASK",
           resource_id=task.id, after={**_snapshot(task), "handover_id": task.handover_id,
                                       "checklist": len(checklist)})
    return task


def quick_add(db: Session, actor: User, handover_id: int, req: dict[str, Any],
              ctx: RequestContext | None = None) -> Task:
    """인수인계에서 바로 만들기(FR-D-06). 비운 칸은 인수인계의 관계사·제목·내용·중요도로."""
    from app.services import handover_service

    handover = handover_service.get_or_404(db, handover_id, actor)
    content = (handover.content or "").strip()
    excerpt = content[:EXCERPT] + ("…" if len(content) > EXCERPT else "")
    return create(db, actor, {
        "title": req.get("title") or handover.title,
        "description": req["description"] if req.get("description") is not None else (excerpt or None),
        "priority_code": req.get("priority_code") or handover.priority_code,
        "assignee_id": req.get("assignee_id"),
        "company_id": handover.company_id,
        "handover_id": handover.id,
        "due_date": req.get("due_date"),
        "checklist": req.get("checklist") or [],
    }, ctx)


def update(db: Session, actor: User, task_id: int, expected_version: int,
           changes: dict[str, Any], ctx: RequestContext | None = None) -> Task:
    task = get_or_404(db, task_id)
    _require_edit(actor, task)
    _check_version(task, expected_version)
    _check_refs(db, priority_code=changes.get("priority_code"),
                assignee_id=changes.get("assignee_id"), company_id=changes.get("company_id"))

    before = _snapshot(task)
    old_assignee, old_status = task.assignee_id, task.status
    for key, value in changes.items():
        if key == "status":
            _set_status(task, value)
        else:
            setattr(task, key, value)
    if task.start_date and task.due_date and task.due_date < task.start_date:
        raise ValidationFailed("마감일이 시작일보다 빠를 수 없습니다.")

    after = _snapshot(task)
    changed = [k for k in TRACKED if before[k] != after[k]]
    if not changed:
        return task                        # 같은 값으로 저장 — 버전도 이력도 늘리지 않는다
    if task.status != old_status:
        task.board_order = _bottom_of(db, task.status)
    task.version_no += 1
    db.flush()

    if task.assignee_id != old_assignee:
        _notify_assignee(db, task, actor)
    completed = task.status == TASK_DONE and old_status != TASK_DONE
    record(db, action=actions.TASK_COMPLETE if completed else actions.TASK_UPDATE, ctx=ctx,
           user=actor, resource_type="TASK", resource_id=task.id,
           before={k: before[k] for k in changed}, after={k: after[k] for k in changed})
    return task


def move(db: Session, actor: User, task_id: int, expected_version: int, status: str,
         after_id: int | None, ctx: RequestContext | None = None) -> Task:
    """보드 끌어놓기. 옮겨 간 칸의 순서를 다시 매긴다(완료 칸은 완료 시각순이라 매기지 않는다)."""
    task = get_or_404(db, task_id)
    _require_edit(actor, task)
    _check_version(task, expected_version)
    old_status = task.status
    _set_status(task, status)

    if status != TASK_DONE:
        column = [t for t in db.scalars(
            select(Task).where(Task.status == status, Task.is_deleted == false(), Task.id != task.id)
            .order_by(Task.board_order, Task.id))]
        index = 0
        if after_id is not None:
            ids = [t.id for t in column]
            index = ids.index(after_id) + 1 if after_id in ids else len(column)
        column.insert(index, task)
        for order, item in enumerate(column):
            item.board_order = order
    task.version_no += 1
    db.flush()

    if status != old_status:
        record(db, action=actions.TASK_COMPLETE if status == TASK_DONE else actions.TASK_UPDATE,
               ctx=ctx, user=actor, resource_type="TASK", resource_id=task.id,
               before={"status": old_status}, after={"status": status, "via": "board"})
    return task


def delete(db: Session, actor: User, task_id: int, reason: str | None,
           ctx: RequestContext | None = None) -> None:
    task = get_or_404(db, task_id)
    if not can_delete(actor, task):
        raise Forbidden("본인이 만든 할일만 삭제할 수 있습니다.")
    task.is_deleted, task.deleted_at, task.deleted_by = True, now(), actor.id
    task.version_no += 1
    db.flush()
    record(db, action=actions.TASK_DELETE, ctx=ctx, user=actor, resource_type="TASK",
           resource_id=task.id, before=_snapshot(task), after={"reason": reason})


# --------------------------------------------------------------------------- 체크리스트

def _checklist_or_404(db: Session, item_id: int) -> tuple[TaskChecklist, Task]:
    item = db.get(TaskChecklist, item_id)
    if item is None:
        raise NotFound("체크리스트 항목을 찾을 수 없습니다.")
    return item, get_or_404(db, item.task_id)


def add_checklist(db: Session, actor: User, task_id: int, title: str) -> TaskChecklist:
    task = get_or_404(db, task_id)
    _require_edit(actor, task)
    order = max((c.sort_order for c in task.checklists), default=-1) + 1
    item = TaskChecklist(task_id=task.id, title=title.strip()[:200], sort_order=order)
    db.add(item)
    db.flush()
    db.refresh(task)
    return item


def update_checklist(db: Session, actor: User, item_id: int, changes: dict[str, Any]) -> TaskChecklist:
    item, task = _checklist_or_404(db, item_id)
    _require_edit(actor, task)
    if "title" in changes and changes["title"] is not None:
        item.title = changes["title"].strip()[:200]
    if "sort_order" in changes and changes["sort_order"] is not None:
        item.sort_order = changes["sort_order"]
    if "is_done" in changes and changes["is_done"] is not None and changes["is_done"] != item.is_done:
        item.is_done = changes["is_done"]
        item.done_at, item.done_by = (now(), actor.id) if item.is_done else (None, None)
    db.flush()
    return item


def delete_checklist(db: Session, actor: User, item_id: int) -> None:
    item, task = _checklist_or_404(db, item_id)
    _require_edit(actor, task)
    db.delete(item)
    db.flush()


# --------------------------------------------------------------------------- 댓글

def list_comments(db: Session, task_id: int) -> list[TaskComment]:
    get_or_404(db, task_id)
    return list(db.scalars(select(TaskComment)
                           .where(TaskComment.task_id == task_id, TaskComment.is_deleted == false())
                           .order_by(TaskComment.created_at, TaskComment.id)))


def add_comment(db: Session, actor: User, task_id: int, body: str) -> TaskComment:
    task = get_or_404(db, task_id)
    comment = TaskComment(task_id=task.id, author_id=actor.id, body=body.strip())
    db.add(comment)
    db.flush()
    for user_id in {task.assignee_id, task.creator_id} - {None, actor.id}:
        notification_service.notify(
            db, user_id=user_id, type_=notification_service.T_TASK_COMMENT,
            title=f"할일에 댓글: {task.title}", body=f"{actor.display_name}: {comment.body[:100]}",
            link_type="TASK", link_id=task.id, dedup_key=f"task-comment:{task.id}")
    return comment


def can_delete_comment(actor: User, comment: TaskComment) -> bool:
    return comment.author_id == actor.id or has_permission(actor.role_code, "task:update_any")


def delete_comment(db: Session, actor: User, comment_id: int) -> None:
    comment = db.get(TaskComment, comment_id)
    if comment is None or comment.is_deleted:
        raise NotFound("댓글을 찾을 수 없습니다.")
    if not can_delete_comment(actor, comment):
        raise Forbidden("본인이 쓴 댓글만 지울 수 있습니다.")
    comment.is_deleted = True
    db.flush()


# --------------------------------------------------------------------------- 목록 · 보드

def _assignee_filter(stmt, actor: User, assignee: str | int):
    if assignee == "me":
        return stmt.where(Task.assignee_id == actor.id)
    if assignee == "unassigned":
        return stmt.where(Task.assignee_id.is_(None))
    if isinstance(assignee, int):
        return stmt.where(Task.assignee_id == assignee)
    return stmt


def search(db: Session, actor: User, req) -> tuple[list[Task], int]:
    stmt = select(Task).where(Task.is_deleted == false())
    if req.status:
        stmt = stmt.where(Task.status.in_(req.status))
    elif not req.include_closed:
        stmt = stmt.where(Task.status.notin_(TASK_CLOSED_STATES))
    stmt = _assignee_filter(stmt, actor, req.assignee)
    if req.created_by_me:
        stmt = stmt.where(Task.creator_id == actor.id)
    if req.company_id is not None:
        stmt = stmt.where(Task.company_id == req.company_id)
    if req.handover_id is not None:
        stmt = stmt.where(Task.handover_id == req.handover_id)
    if req.q and req.q.strip():
        term = req.q.strip()
        stmt = stmt.where(or_(Task.title.icontains(term, autoescape=True),
                              Task.description.icontains(term, autoescape=True)))
    t0 = today()
    if req.due == "overdue":
        stmt = stmt.where(Task.due_date < t0, Task.status.notin_(TASK_CLOSED_STATES))
    elif req.due == "today":
        stmt = stmt.where(Task.due_date == t0)
    elif req.due == "this_week":
        stmt = stmt.where(Task.due_date >= t0, Task.due_date <= week_start(t0) + timedelta(days=6))
    elif req.due == "none":
        stmt = stmt.where(Task.due_date.is_(None))

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    level = select(Priority.level).where(Priority.code == Task.priority_code).scalar_subquery()
    order = {
        "due_date": (Task.due_date.is_(None), Task.due_date, level, Task.id),
        "updated_at": (Task.updated_at.desc(), Task.id.desc()),
        "priority": (level, Task.due_date.is_(None), Task.due_date, Task.id),
        "created_at": (Task.created_at.desc(), Task.id.desc()),
    }[req.sort]
    rows = list(db.scalars(stmt.order_by(*order).offset((req.page - 1) * req.size).limit(req.size)))
    return rows, total


def board(db: Session, actor: User, assignee: str | int = "all",
          company_id: int | None = None) -> dict[str, Any]:
    base = _assignee_filter(select(Task).where(Task.is_deleted == false()), actor, assignee)
    if company_id is not None:
        base = base.where(Task.company_id == company_id)
    since = today() - timedelta(days=DONE_WINDOW_DAYS)
    columns: dict[str, list[Task]] = {}
    for status in (TASK_TODO, TASK_IN_PROGRESS, TASK_WAITING):
        columns[status] = list(db.scalars(base.where(Task.status == status)
                                          .order_by(Task.board_order, Task.id)))
    columns[TASK_DONE] = list(db.scalars(
        base.where(Task.status == TASK_DONE,
                   Task.completed_at >= datetime.combine(since, time.min, tzinfo=KST))
        .order_by(Task.completed_at.desc(), Task.id.desc()).limit(100)))
    return {"columns": columns, "since": since}


def for_handover(db: Session, handover_id: int) -> list[Task]:
    """인수인계에 딸린 할일 — 안 끝난 것 먼저."""
    closed_last = Task.status.in_(TASK_CLOSED_STATES)
    return list(db.scalars(select(Task)
                           .where(Task.handover_id == handover_id, Task.is_deleted == false())
                           .order_by(closed_last, Task.due_date.is_(None), Task.due_date, Task.id)))


def count_for_handover(db: Session, handover_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Task)
                     .where(Task.handover_id == handover_id, Task.is_deleted == false())) or 0


# --------------------------------------------------------------------------- 응답

def to_out(db: Session, actor: User, tasks: list[Task], *, detail: bool = False) -> list[dict]:
    """한 페이지를 한 번에 — 댓글 수를 행마다 세지 않는다."""
    ids = [t.id for t in tasks]
    comments = dict(db.execute(
        select(TaskComment.task_id, func.count())
        .where(TaskComment.task_id.in_(ids), TaskComment.is_deleted == false())
        .group_by(TaskComment.task_id)).all()) if ids else {}
    t0 = today()
    out = []
    for t in tasks:
        row = {
            "id": t.id, "title": t.title, "description": t.description, "status": t.status,
            "priority": t.priority, "assignee": t.assignee, "creator": t.creator,
            "company": t.company,
            "handover": ({"id": t.handover.id, "title": t.handover.title,
                          "is_deleted": t.handover.is_deleted} if t.handover else None),
            "start_date": t.start_date, "due_date": t.due_date, "completed_at": t.completed_at,
            "board_order": t.board_order, "version_no": t.version_no,
            "is_overdue": is_overdue(t, t0),
            "checklist_total": len(t.checklists),
            "checklist_done": sum(1 for c in t.checklists if c.is_done),
            "comment_count": comments.get(t.id, 0),
            "can_edit": can_edit(actor, t),
            "created_at": t.created_at, "updated_at": t.updated_at,
        }
        if detail:
            row["checklists"] = list(t.checklists)
        out.append(row)
    return out
