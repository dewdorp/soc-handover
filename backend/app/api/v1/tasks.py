"""할일 · 체크리스트 · 댓글 · 내 업무 라우터 (API.md §5). 규칙은 services/task_service.py 에 있다.

구체적인 경로(/tasks/search, /tasks/board)를 /tasks/{task_id} 보다 먼저 선언한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import require, require_password_changed
from app.core.context import RequestContext, get_context
from app.core.db import get_db
from app.core.errors import ValidationFailed
from app.models.user import User
from app.schemas.task import (BoardOut, ChecklistCreate, ChecklistOut, ChecklistUpdate,
                              CommentCreate, CommentOut, DeleteTaskRequest, MyWorkBucket,
                              MyWorkOut, MyWorkSource, QuickAddRequest, TaskCreate, TaskDetail,
                              TaskMove, TaskOut, TaskPage, TaskSearchRequest, TaskUpdate)
from app.services import my_work_service
from app.services import task_service as svc

router = APIRouter(tags=["tasks"], dependencies=[Depends(require_password_changed)])


def _detail(db: Session, actor: User, task) -> dict:
    return svc.to_out(db, actor, [task], detail=True)[0]


def _assignee_param(value: str) -> str | int:
    if value in ("me", "all", "unassigned"):
        return value
    if value.isdigit():
        return int(value)
    raise ValidationFailed("assignee 는 me · all · unassigned · 사용자 번호 중 하나입니다.")


# --------------------------------------------------------------------------- 목록 · 보드

@router.post("/tasks/search", response_model=TaskPage)
def search_tasks(payload: TaskSearchRequest, db: Session = Depends(get_db),
                 actor: User = Depends(require("task:read"))):
    rows, total = svc.search(db, actor, payload)
    return {"items": svc.to_out(db, actor, rows), "total": total,
            "page": payload.page, "size": payload.size}


@router.get("/tasks/board", response_model=BoardOut)
def task_board(assignee: str = Query(default="all", max_length=20),
               company_id: int | None = None, db: Session = Depends(get_db),
               actor: User = Depends(require("task:read"))):
    """할일 · 진행중 · 대기 · 완료(최근 14일) 네 칸(FR-D-03·05)."""
    data = svc.board(db, actor, _assignee_param(assignee), company_id)
    columns = {k: svc.to_out(db, actor, v) for k, v in data["columns"].items()}
    return {"columns": columns, "counts": {k: len(v) for k, v in columns.items()},
            "done_since": data["since"]}


# --------------------------------------------------------------------------- 할일

@router.post("/tasks", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                actor: User = Depends(require("task:create")),
                ctx: RequestContext = Depends(get_context)):
    task = svc.create(db, actor, payload.model_dump(), ctx)
    return _detail(db, actor, task)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: int, db: Session = Depends(get_db),
             actor: User = Depends(require("task:read"))):
    return _detail(db, actor, svc.get_or_404(db, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require("task:update")),
                ctx: RequestContext = Depends(get_context)):
    task = svc.update(db, actor, task_id, payload.expected_version, payload.changes(), ctx)
    return _detail(db, actor, task)


@router.patch("/tasks/{task_id}/move", response_model=TaskOut)
def move_task(task_id: int, payload: TaskMove, db: Session = Depends(get_db),
              actor: User = Depends(require("task:update")),
              ctx: RequestContext = Depends(get_context)):
    task = svc.move(db, actor, task_id, payload.expected_version, payload.status,
                    payload.after_id, ctx)
    return svc.to_out(db, actor, [task])[0]


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, payload: DeleteTaskRequest | None = Body(default=None),
                db: Session = Depends(get_db), actor: User = Depends(require("task:read")),
                ctx: RequestContext = Depends(get_context)):
    svc.delete(db, actor, task_id, payload.reason if payload else None, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- 체크리스트

@router.post("/tasks/{task_id}/checklists", response_model=ChecklistOut,
             status_code=status.HTTP_201_CREATED)
def add_checklist(task_id: int, payload: ChecklistCreate, db: Session = Depends(get_db),
                  actor: User = Depends(require("task:update"))):
    return svc.add_checklist(db, actor, task_id, payload.title)


@router.patch("/checklists/{item_id}", response_model=ChecklistOut)
def update_checklist(item_id: int, payload: ChecklistUpdate, db: Session = Depends(get_db),
                     actor: User = Depends(require("task:update"))):
    return svc.update_checklist(db, actor, item_id, payload.model_dump(exclude_unset=True))


@router.delete("/checklists/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_checklist(item_id: int, db: Session = Depends(get_db),
                     actor: User = Depends(require("task:update"))):
    svc.delete_checklist(db, actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- 댓글

def _comment_out(db: Session, actor: User, comment) -> dict:
    author = db.get(User, comment.author_id) if comment.author_id else None
    return {"id": comment.id, "body": comment.body, "author_id": comment.author_id,
            "author": author.display_name if author else None, "created_at": comment.created_at,
            "can_delete": svc.can_delete_comment(actor, comment)}


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
def list_comments(task_id: int, db: Session = Depends(get_db),
                  actor: User = Depends(require("task:read"))):
    return [_comment_out(db, actor, c) for c in svc.list_comments(db, task_id)]


@router.post("/tasks/{task_id}/comments", response_model=CommentOut,
             status_code=status.HTTP_201_CREATED)
def add_comment(task_id: int, payload: CommentCreate, db: Session = Depends(get_db),
                actor: User = Depends(require("task:create"))):
    return _comment_out(db, actor, svc.add_comment(db, actor, task_id, payload.body))


@router.delete("/task-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("task:read"))):
    svc.delete_comment(db, actor, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- 인수인계 연계

@router.get("/handovers/{handover_id}/tasks", response_model=list[TaskOut])
def handover_tasks(handover_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require("task:read"))):
    return svc.to_out(db, actor, svc.for_handover(db, handover_id))


@router.post("/handovers/{handover_id}/tasks", response_model=TaskDetail,
             status_code=status.HTTP_201_CREATED)
def quick_add(handover_id: int, payload: QuickAddRequest, db: Session = Depends(get_db),
              actor: User = Depends(require("task:create")),
              ctx: RequestContext = Depends(get_context)):
    """인수인계에서 바로 만들기(FR-D-06). 관계사·연결·제목·내용 일부·중요도를 채운다."""
    task = svc.quick_add(db, actor, handover_id, payload.model_dump(exclude_unset=True), ctx)
    return _detail(db, actor, task)


# --------------------------------------------------------------------------- 내 업무

@router.get("/my-work", response_model=MyWorkOut)
def my_work(bucket: MyWorkBucket = "all", source: MyWorkSource = "all",
            db: Session = Depends(get_db), actor: User = Depends(require("task:read"))):
    return my_work_service.my_work(db, actor, bucket, source)
