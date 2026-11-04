"""내 메모. 모든 조회·변경에 로그인 계정의 소유권 조건을 적용한다."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.core.db import get_db
from app.core.errors import AppError, NotFound, VersionConflict
from app.core.time import utcnow
from app.models.private_note import PrivateNote
from app.models.user import User
from app.schemas.private_note import NoteCreate, NoteOut, NotePatch


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


class NoteSessionChanged(AppError):
    code = "session_changed"
    status_code = 412
    message = "로그인 계정이 변경되었습니다. 화면을 새로 고쳐 주세요."


def _note_actor(user: Annotated[User, Depends(require_password_changed)],
                expected_user_id: Annotated[int | None, Header(alias="X-Expected-User-ID")] = None) -> User:
    if expected_user_id is not None and expected_user_id != user.id:
        raise NoteSessionChanged()
    return user


router = APIRouter(prefix="/me/notes", tags=["내 메모"], dependencies=[Depends(_no_store)])
Actor = Annotated[User, Depends(_note_actor)]
Database = Annotated[Session, Depends(get_db)]


def _owned(note_id: int, user: User):
    return (PrivateNote.id == note_id) & (PrivateNote.owner_id == user.id)


def _failed_write(db: Session, note_id: int, user: User) -> None:
    if db.scalar(select(PrivateNote.id).where(_owned(note_id, user))) is None:
        raise NotFound()
    raise VersionConflict("다른 창에서 메모를 수정했습니다. 최신 내용을 확인하십시오.")


@router.get("", response_model=list[NoteOut])
def list_notes(user: Actor, db: Database):
    return db.scalars(select(PrivateNote).where(PrivateNote.owner_id == user.id)
                      .order_by(PrivateNote.updated_at.desc(), PrivateNote.id.desc())).all()


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, user: Actor, db: Database):
    note = db.scalar(select(PrivateNote).where(_owned(note_id, user)))
    if note is None:
        raise NotFound()
    return note


@router.post("", response_model=NoteOut, status_code=201)
def create_note(data: NoteCreate, user: Actor, db: Database):
    timestamp = utcnow()
    note = PrivateNote(owner_id=user.id, title=data.title, body=data.body,
                       created_at=timestamp, updated_at=timestamp)
    db.add(note)
    db.flush()
    return note


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(note_id: int, data: NotePatch, user: Actor, db: Database):
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    stmt = (update(PrivateNote).where(_owned(note_id, user), PrivateNote.version_no == data.expected_version)
            .values(**changes, updated_at=utcnow(), version_no=PrivateNote.version_no + 1).returning(PrivateNote))
    note = db.scalar(stmt)
    if note is None:
        _failed_write(db, note_id, user)
    return note


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, expected_version: Annotated[int, Query(ge=1)], user: Actor, db: Database):
    stmt = delete(PrivateNote).where(_owned(note_id, user), PrivateNote.version_no == expected_version)
    if db.execute(stmt).rowcount == 0:
        _failed_write(db, note_id, user)
