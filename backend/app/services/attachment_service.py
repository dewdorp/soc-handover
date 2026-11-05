"""첨부파일 (FR-I-04) — 인수인계 · 할일에 파일을 붙인다.

- 확장자 허용 목록(attachment.allowed_ext)과 크기(attachment.max_size_mb)는 관리 설정.
  허용 목록에 있어도 실행 · 스크립트 형식(BLOCKED_EXT)은 다시 막는다.
- 저장: DATA_DIR/attachments/YYYY/MM/<무작위 이름> — 확장자를 붙이지 않아 서버에서 실행될 일이
  없고, 원래 이름은 DB 에만 둔다. 받을 때는 원래 이름으로 내려보낸다.
- 크기는 받으면서 센다 — 한도를 넘는 순간 멈추고 지운다(요청 헤더의 크기를 믿지 않는다).
- 올리기 · 지우기는 대상을 고칠 수 있는 사람(또는 올린 본인의 지우기). 받기는 볼 수 있는 사람.
- 지우기는 표시만 하고 파일은 남긴다(증적). 올리기 · 받기 · 지우기 모두 감사에 남긴다.
- 백신 연동 확장점: scan() — ATTACHMENT_SCAN_COMMAND(.env) 가 비어 있으면 검사하지 않음(NOT_SCANNED).
  명령이 있으면 파일 경로로 실행해 종료코드 0 이면 CLEAN, 아니면 거절. 실행이 실패해도 거절한다.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import can_edit_handover
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import now
from app.models.common import Attachment
from app.models.handover import Handover
from app.models.task import Task
from app.models.user import User
from app.services import settings_service

log = logging.getLogger("app.attachment")
ENTITY_TYPES = ("HANDOVER", "TASK")
CHUNK = 1024 * 1024
_UNSAFE = re.compile(r'[\x00-\x1f<>:"|?*]')

#: 화면에서 그대로 보여 줘도 되는 그림 — 파일 **내용**의 앞부분으로 판단한다.
#: 이름 · 확장자 · 올릴 때 추측한 mime 은 믿지 않는다(내용이 HTML 인 'x.png' 을 그대로
#: 내보내면 브라우저가 실행할 수 있다). SVG 는 스크립트를 품을 수 있어 넣지 않는다
#: (BLOCKED_EXT 에서 올리는 것부터 막는다).
IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
SNIFF_BYTES = 16


def _entity(db: Session, entity_type: str, entity_id: int, actor: User | None = None):
    """첨부의 주인 되는 대상. actor 를 주면 **열람 그룹까지** 확인한다.

    첨부는 원문의 일부다. 원문을 못 보는 사람이 파일 번호만 알아내 받아 가는 길을 막는다.
    """
    model = {"HANDOVER": Handover, "TASK": Task}.get(entity_type)
    if model is None:
        raise ValidationFailed("첨부는 인수인계(HANDOVER) · 할일(TASK)에만 붙일 수 있습니다.")
    obj = db.get(model, entity_id)
    if obj is None or obj.is_deleted:
        raise NotFound("첨부할 대상을 찾을 수 없습니다.")
    if actor is not None:
        _guard_read(db, entity_type, obj, actor)
    return obj


def _guard_read(db: Session, entity_type: str, obj, actor: User) -> None:
    from app.services import group_service

    if entity_type == "HANDOVER":
        group_service.assert_visible(db, obj, actor)
        return
    # 할일에 붙은 첨부: 인수인계에서 만들어진 할일이면 그 원문 범위를 따른다.
    if getattr(obj, "handover_id", None):
        handover = db.get(Handover, obj.handover_id)
        if handover is not None:
            group_service.assert_visible(db, handover, actor)


def _can_modify(actor: User, entity_type: str, obj) -> bool:
    if entity_type == "HANDOVER":
        return can_edit_handover(role_code=actor.role_code, user_id=actor.id,
                                 creator_id=obj.created_by, assignee_id=obj.assignee_id)
    from app.services import task_service
    return task_service.can_edit(actor, obj)


def safe_name(name: str) -> str:
    """경로 부분을 떼고 제어문자 · 예약문자를 지운다."""
    base = re.split(r"[\\/]", name or "")[-1].strip().strip(".")
    base = _UNSAFE.sub("_", base)
    return (base or "file")[:200]


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def scan(path: Path) -> str:
    """백신 검사. 명령이 없으면 NOT_SCANNED, 있으면 CLEAN — 위험이거나 실행 실패면 예외."""
    command = settings.ATTACHMENT_SCAN_COMMAND.strip()
    if not command:
        return "NOT_SCANNED"
    args = [a.replace("{path}", str(path)) for a in shlex.split(command, posix=False)]
    args = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in args]
    try:
        done = subprocess.run(args, capture_output=True, timeout=settings.ATTACHMENT_SCAN_TIMEOUT_SEC,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("attachment scan failed to run: %s", exc)
        raise ValidationFailed("백신 검사를 하지 못해 올리지 않았습니다. 관리자에게 문의하십시오.") from exc
    if done.returncode != 0:
        log.warning("attachment scan rejected file (exit %s)", done.returncode)
        raise ValidationFailed("백신 검사에서 위험한 파일로 판정되어 올리지 않았습니다.")
    return "CLEAN"


def upload(db: Session, actor: User, entity_type: str, entity_id: int, file_name: str, stream: BinaryIO,
           ctx: RequestContext | None = None) -> Attachment:
    entity_type = entity_type.upper()
    obj = _entity(db, entity_type, entity_id, actor)
    if not _can_modify(actor, entity_type, obj):
        raise Forbidden("이 대상을 고칠 수 있는 사람만 첨부할 수 있습니다.")

    name = safe_name(file_name)
    ext = _ext(name)
    allowed = [str(x).lower() for x in (settings_service.get_value(db, "attachment.allowed_ext") or [])]
    if not ext or ext not in allowed or ext in settings_service.BLOCKED_EXT:
        raise ValidationFailed(f"'{ext or '확장자 없음'}' 파일은 올릴 수 없습니다. 허용: {', '.join(allowed)}",
                               detail={"allowed": allowed})
    max_mb = int(settings_service.get_value(db, "attachment.max_size_mb") or settings.UPLOAD_MAX_MB)
    max_bytes = max_mb * 1024 * 1024

    sub = now().strftime("%Y/%m")
    stored = uuid.uuid4().hex
    folder = settings.attachments_dir / sub
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / stored
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationFailed(f"파일이 너무 큽니다. {max_mb}MB 까지 올릴 수 있습니다.")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ValidationFailed("빈 파일은 올릴 수 없습니다.")
        status = scan(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    att = Attachment(entity_type=entity_type, entity_id=entity_id, original_name=name, stored_name=stored,
                     rel_path=f"{sub}/{stored}", mime=mimetypes.guess_type(name)[0] or "application/octet-stream",
                     size_bytes=size, sha256=digest.hexdigest(), scan_status=status, uploaded_by=actor.id)
    db.add(att)
    db.flush()
    record(db, action=actions.ATTACHMENT_UPLOAD, ctx=ctx, user=actor, resource_type=entity_type,
           resource_id=entity_id, after={"attachment_id": att.id, "name": name, "size": size,
                                         "sha256": att.sha256, "scan": status})
    return att


def get_or_404(db: Session, attachment_id: int) -> Attachment:
    att = db.get(Attachment, attachment_id)
    if att is None or att.is_deleted:
        raise NotFound("첨부파일을 찾을 수 없습니다.")
    return att


def file_path(att: Attachment) -> Path:
    """DB 의 상대 경로가 첨부 폴더 밖을 가리키지 않는지 확인한다."""
    root = settings.attachments_dir.resolve()
    path = (root / att.rel_path).resolve()
    if root not in path.parents or not path.is_file():
        raise NotFound("첨부파일이 저장소에 없습니다. 관리자에게 문의하십시오.")
    return path


def image_type(path: Path) -> str | None:
    """그림이면 내보낼 미디어 타입, 아니면 None."""
    try:
        with path.open("rb") as f:
            head = f.read(SNIFF_BYTES)
    except OSError:
        return None
    for magic, mime in IMAGE_MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_image(att: Attachment) -> bool:
    """목록에서 '미리 볼 수 있는가'. 파일이 없거나 그림이 아니면 False."""
    try:
        return image_type(file_path(att)) is not None
    except NotFound:
        return False


def preview(db: Session, attachment_id: int, actor: User) -> tuple[Path, Attachment, str]:
    """그림을 화면에 그대로 보여 주기 위한 경로 · 타입.

    내려받기와 달리 감사에 남기지 않는다 — 인수인계 화면을 여는 것과 같은 행위이고,
    그림 하나에 요청이 여러 번 갈 수 있어 남기면 감사로그가 이것으로 채워진다.
    파일을 손에 넣는 '받기'는 그대로 감사에 남는다(ASSUMPTIONS I-02).
    """
    att = get_or_404(db, attachment_id)
    _entity(db, att.entity_type, att.entity_id, actor)
    path = file_path(att)
    mime = image_type(path)
    if mime is None:
        raise ValidationFailed("미리 볼 수 있는 그림이 아닙니다. 내려받아서 여십시오.")
    return path, att, mime


def download(db: Session, actor: User, attachment_id: int, ctx: RequestContext | None = None) -> tuple[Path, Attachment]:
    att = get_or_404(db, attachment_id)
    _entity(db, att.entity_type, att.entity_id, actor)
    path = file_path(att)
    record(db, action=actions.ATTACHMENT_DOWNLOAD, ctx=ctx, user=actor, resource_type=att.entity_type,
           resource_id=att.entity_id, detail={"attachment_id": att.id, "name": att.original_name})
    return path, att


def can_delete(db: Session, actor: User, att: Attachment) -> bool:
    if att.uploaded_by == actor.id:
        return True
    try:
        obj = _entity(db, att.entity_type, att.entity_id)
    except NotFound:
        return False
    return _can_modify(actor, att.entity_type, obj)


def delete(db: Session, actor: User, attachment_id: int, ctx: RequestContext | None = None) -> None:
    att = get_or_404(db, attachment_id)
    _entity(db, att.entity_type, att.entity_id, actor)
    if not can_delete(db, actor, att):
        raise Forbidden("올린 사람이나 대상을 고칠 수 있는 사람만 지울 수 있습니다.")
    att.is_deleted = True
    db.flush()
    record(db, action=actions.ATTACHMENT_DELETE, ctx=ctx, user=actor, resource_type=att.entity_type,
           resource_id=att.entity_id, before={"attachment_id": att.id, "name": att.original_name,
                                              "sha256": att.sha256})


def list_for(db: Session, entity_type: str, entity_id: int,
             actor: User | None = None) -> list[Attachment]:
    _entity(db, entity_type.upper(), entity_id, actor)
    return list(db.scalars(select(Attachment).where(
        Attachment.entity_type == entity_type.upper(), Attachment.entity_id == entity_id,
        Attachment.is_deleted == false()).order_by(Attachment.created_at, Attachment.id)))


def count_for(db: Session, entity_type: str, entity_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Attachment).where(
        Attachment.entity_type == entity_type, Attachment.entity_id == entity_id,
        Attachment.is_deleted == false())) or 0


def to_out(db: Session, actor: User, att: Attachment) -> dict[str, Any]:
    uploader = db.get(User, att.uploaded_by) if att.uploaded_by else None
    return {"id": att.id, "entity_type": att.entity_type, "entity_id": att.entity_id,
            "name": att.original_name, "size": att.size_bytes, "mime": att.mime, "sha256": att.sha256,
            "scan_status": att.scan_status, "uploaded_by": uploader.display_name if uploader else None,
            "created_at": att.created_at, "can_delete": can_delete(db, actor, att),
            "is_image": is_image(att)}
