"""인수인계 도메인 서비스 — 생성/수정/삭제/복원과 Version 기록.

불변 규칙
  1. 모든 내용 변경은 새 Version 을 만든다. 기존 Version 은 절대 수정/삭제하지 않는다.
  2. after_data 는 **변경 후 전체 스냅샷**이다. 어느 버전 한 줄만으로 그 시점을 재현할 수 있다.
  3. before_data 는 **변경된 필드의 이전 값만** 담는다. 전체 이전 상태는 v(n-1).after_data 가 갖고
     있으므로 손실이 없고, 저장량이 두 배로 늘지 않는다.
  4. 값이 실제로 달라지지 않았으면 Version 을 만들지 않는다(no-op).
  5. 수정은 expected_version 비교 → 불일치 시 409. 조용히 덮어쓰지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.auth.rbac import can_edit_handover, has_permission
from app.core.context import RequestContext
from app.core.db import dialect_name
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.core.time import now
from app.models.handover import (CHANGE_CREATE, CHANGE_DELETE, CHANGE_RESTORE, CHANGE_UNDELETE,
                                 CHANGE_UPDATE, VERSIONED_FIELDS, Handover,
                                 HandoverComment, HandoverStar, HandoverTag, HandoverVersion)
from app.models.reference import Company, HandoverStatus, Priority, Tag
from app.models.user import User
from app.services import ack_service
from app.utils.diff import field_diff

_DATE_FIELDS = frozenset({"registered_date", "work_date"})
_DATETIME_FIELDS = frozenset({"completed_at"})
_USER_FIELDS = frozenset({"sender_id", "assignee_id", "checker_id"})


# --------------------------------------------------------------------------- 스냅샷

def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def tag_names(handover: Handover) -> list[str]:
    return sorted(link.tag.name for link in handover.tag_links if link.tag is not None)


def snapshot(handover: Handover) -> dict[str, Any]:
    """VERSIONED_FIELDS 전체를 JSON 으로 안전한 형태로 뽑는다."""
    data: dict[str, Any] = {}
    for field in VERSIONED_FIELDS:
        if field == "tags":
            data[field] = tag_names(handover)
        else:
            data[field] = _jsonable(getattr(handover, field))
    return data


def _coerce(field: str, value: Any) -> Any:
    """after_data(JSON) 값을 ORM 이 받을 수 있는 파이썬 타입으로 되돌린다(복원용)."""
    if value is None:
        return None
    if field in _DATE_FIELDS and isinstance(value, str):
        return date.fromisoformat(value)
    if field in _DATETIME_FIELDS and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def changed_between(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """VERSIONED_FIELDS 순서를 유지한 변경 필드 목록."""
    return [f for f in VERSIONED_FIELDS if before.get(f) != after.get(f)]


def build_search_text(db: Session, handover: Handover) -> str:
    """제목+내용+비고+관계사+인명+태그 결합 텍스트. PG 에서는 tsvector 의 원천이 된다."""
    parts: list[str] = [handover.title or "", handover.content or "", handover.remark or ""]

    company = db.get(Company, handover.company_id)
    if company is not None:
        parts.append(company.name)
        if company.short_name:
            parts.append(company.short_name)

    for uid_field, raw_field in (("sender_id", "sender_name_raw"),
                                 ("assignee_id", "assignee_name_raw"),
                                 ("checker_id", "checker_name_raw")):
        uid = getattr(handover, uid_field)
        if uid:
            user = db.get(User, uid)
            if user is not None:
                parts.append(user.display_name)
        raw = getattr(handover, raw_field)
        if raw:
            parts.append(raw)

    parts.extend(tag_names(handover))
    return " ".join(p for p in parts if p).strip()


# --------------------------------------------------------------------------- 조회

def _select_one(db: Session, handover_id: int, *, lock: bool = False) -> Handover | None:
    stmt = select(Handover).where(Handover.id == handover_id)
    if lock and dialect_name() == "postgresql":
        # SQLite 는 FOR UPDATE 가 없다(단일 writer 로 직렬화됨). PG 에서만 행을 잠근다.
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def get_or_404(db: Session, handover_id: int, actor: User, *, lock: bool = False) -> Handover:
    row = _select_one(db, handover_id, lock=lock)
    if row is None:
        raise NotFound("인수인계를 찾을 수 없습니다.")
    if row.is_deleted and not has_permission(actor.role_code, "handover:read_deleted"):
        # 삭제된 건의 존재 자체를 드러내지 않는다.
        raise NotFound("인수인계를 찾을 수 없습니다.")
    return row


def _ensure_editable(handover: Handover, actor: User) -> None:
    if not can_edit_handover(role_code=actor.role_code, user_id=actor.id,
                             creator_id=handover.created_by,
                             assignee_id=handover.assignee_id):
        raise Forbidden("본인이 작성했거나 담당자로 지정된 건만 수정할 수 있습니다.")


# --------------------------------------------------------------------------- 참조 무결성

def _validate_refs(db: Session, *, company_id: int | None, status_code: str | None,
                   priority_code: str | None, user_ids: dict[str, int | None]) -> None:
    if company_id is not None and db.get(Company, company_id) is None:
        raise ValidationFailed("존재하지 않는 관계사입니다.", detail={"field": "company_id"})
    if status_code is not None and db.get(HandoverStatus, status_code) is None:
        raise ValidationFailed("존재하지 않는 상태 코드입니다.", detail={"field": "status_code"})
    if priority_code is not None and db.get(Priority, priority_code) is None:
        raise ValidationFailed("존재하지 않는 중요도 코드입니다.", detail={"field": "priority_code"})
    for field, uid in user_ids.items():
        if uid is not None and db.get(User, uid) is None:
            raise ValidationFailed("존재하지 않는 사용자입니다.", detail={"field": field})


def _apply_tags(db: Session, handover: Handover, names: list[str] | None) -> None:
    """태그 목록을 통째로 교체한다. 사용 횟수도 함께 맞춘다."""
    if names is None:
        return
    wanted = {n.strip() for n in names if n and n.strip()}
    current = {link.tag.name: link for link in handover.tag_links if link.tag is not None}

    for name, link in current.items():
        if name not in wanted:
            tag = db.get(Tag, link.tag_id)
            if tag is not None and tag.usage_count > 0:
                tag.usage_count -= 1
            handover.tag_links.remove(link)

    for name in sorted(wanted - set(current)):
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name, usage_count=0)
            db.add(tag)
            db.flush()
        tag.usage_count += 1
        handover.tag_links.append(HandoverTag(handover_id=handover.id, tag_id=tag.id))
    db.flush()


# --------------------------------------------------------------------------- Version 기록

def _add_version(db: Session, handover: Handover, *, change_type: str,
                 before_data: dict | None, after_data: dict, changed_fields: list[str],
                 change_reason: str | None, actor: User, ctx: RequestContext | None,
                 restored_from: int | None = None) -> HandoverVersion:
    version = HandoverVersion(
        handover_id=handover.id,
        version_no=handover.current_version_no,
        change_type=change_type,
        before_data=before_data,
        after_data=after_data,
        changed_fields=changed_fields,
        change_reason=change_reason,
        restored_from_version=restored_from,
        changed_by=actor.id,
        changed_at=now(),
        client_ip=ctx.client_ip if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
    )
    db.add(version)
    db.flush()
    return version


# --------------------------------------------------------------------------- 생성

def create_handover(db: Session, payload: dict[str, Any], actor: User,
                    ctx: RequestContext | None = None) -> Handover:
    tags = payload.pop("tags", None)
    _validate_refs(db, company_id=payload.get("company_id"),
                   status_code=payload.get("status_code"),
                   priority_code=payload.get("priority_code"),
                   user_ids={f: payload.get(f) for f in _USER_FIELDS})

    handover = Handover(**payload)
    handover.current_version_no = 1
    handover.created_by = actor.id
    handover.updated_by = actor.id
    db.add(handover)
    db.flush()

    _apply_tags(db, handover, tags)
    handover.search_text = build_search_text(db, handover)
    db.flush()

    after = snapshot(handover)
    _add_version(db, handover, change_type=CHANGE_CREATE, before_data=None, after_data=after,
                 changed_fields=list(VERSIONED_FIELDS), change_reason=None,
                 actor=actor, ctx=ctx)
    record(db, action=actions.HANDOVER_CREATE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id, after=after)
    return handover


# --------------------------------------------------------------------------- 수정

def _conflict_detail(db: Session, handover: Handover, expected_version: int,
                     attempted_fields: list[str], current: dict) -> dict[str, Any]:
    """expected_version 이후 실제로 바뀐 필드와, 내가 바꾸려던 필드의 교집합을 알려준다."""
    rows = db.scalars(
        select(HandoverVersion.changed_fields)
        .where(HandoverVersion.handover_id == handover.id,
               HandoverVersion.version_no > expected_version)
    ).all()
    changed_since: set[str] = set()
    for fields in rows:
        changed_since.update(fields or [])
    conflicting = [f for f in VERSIONED_FIELDS
                   if f in changed_since and f in set(attempted_fields)]
    return {
        "current_version_no": handover.current_version_no,
        "expected_version": expected_version,
        "changed_since": sorted(changed_since),
        "conflicting_fields": conflicting,
        "current": current,
    }


def update_handover(db: Session, handover_id: int, changes: dict[str, Any],
                    *, expected_version: int, change_reason: str | None,
                    actor: User, ctx: RequestContext | None = None) -> tuple[Handover, bool]:
    """Returns: (handover, version_created)."""
    handover = get_or_404(db, handover_id, actor, lock=True)
    if handover.is_deleted:
        raise Conflict("삭제된 인수인계는 수정할 수 없습니다. 먼저 복구하십시오.")
    _ensure_editable(handover, actor)

    tags = changes.pop("tags", None)
    attempted = list(changes) + (["tags"] if tags is not None else [])

    if expected_version != handover.current_version_no:
        raise VersionConflict(detail=_conflict_detail(
            db, handover, expected_version, attempted, snapshot(handover)))

    _validate_refs(db, company_id=changes.get("company_id"),
                   status_code=changes.get("status_code"),
                   priority_code=changes.get("priority_code"),
                   user_ids={f: changes.get(f) for f in _USER_FIELDS if f in changes})

    before = snapshot(handover)
    for field, value in changes.items():
        setattr(handover, field, value)
    _apply_tags(db, handover, tags)
    db.flush()

    after = snapshot(handover)
    changed = changed_between(before, after)
    if not changed:
        return handover, False  # no-op — 버전을 만들지 않는다

    handover.current_version_no += 1
    handover.updated_by = actor.id
    handover.search_text = build_search_text(db, handover)
    db.flush()

    _add_version(db, handover, change_type=CHANGE_UPDATE,
                 before_data={f: before[f] for f in changed}, after_data=after,
                 changed_fields=changed, change_reason=change_reason, actor=actor, ctx=ctx)
    reack = ack_service.invalidate_on_change(db, handover, changed)
    record(db, action=actions.HANDOVER_UPDATE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={f: before[f] for f in changed}, after={f: after[f] for f in changed},
           detail={"version_no": handover.current_version_no, "reack_triggered_by": reack})
    return handover, True


# --------------------------------------------------------------------------- 삭제 / 복구

def soft_delete(db: Session, handover_id: int, reason: str, actor: User,
                ctx: RequestContext | None = None) -> Handover:
    handover = get_or_404(db, handover_id, actor, lock=True)
    if handover.is_deleted:
        raise Conflict("이미 삭제된 인수인계입니다.")
    if not reason or not reason.strip():
        raise ValidationFailed("삭제 사유는 필수입니다.", detail={"field": "reason"})

    handover.is_deleted = True
    handover.deleted_at = now()
    handover.deleted_by = actor.id
    handover.delete_reason = reason.strip()
    handover.current_version_no += 1
    db.flush()

    _add_version(db, handover, change_type=CHANGE_DELETE,
                 before_data={"is_deleted": False}, after_data=snapshot(handover),
                 changed_fields=["is_deleted"], change_reason=reason.strip(),
                 actor=actor, ctx=ctx)
    record(db, action=actions.HANDOVER_DELETE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"is_deleted": False}, after={"is_deleted": True},
           detail={"reason": reason.strip(), "version_no": handover.current_version_no})
    return handover


def undelete(db: Session, handover_id: int, actor: User,
             ctx: RequestContext | None = None) -> Handover:
    handover = get_or_404(db, handover_id, actor, lock=True)
    if not handover.is_deleted:
        raise Conflict("삭제되지 않은 인수인계입니다.")

    handover.is_deleted = False
    handover.deleted_at = None
    handover.deleted_by = None
    handover.delete_reason = None
    handover.current_version_no += 1
    db.flush()

    _add_version(db, handover, change_type=CHANGE_UNDELETE,
                 before_data={"is_deleted": True}, after_data=snapshot(handover),
                 changed_fields=["is_deleted"], change_reason=None, actor=actor, ctx=ctx)
    record(db, action=actions.HANDOVER_UNDELETE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={"is_deleted": True}, after={"is_deleted": False})
    return handover


# --------------------------------------------------------------------------- 버전 조회 / 복원

def list_versions(db: Session, handover_id: int) -> list[HandoverVersion]:
    return list(db.scalars(
        select(HandoverVersion)
        .where(HandoverVersion.handover_id == handover_id)
        .order_by(HandoverVersion.version_no.desc())
    ))


def get_version(db: Session, handover_id: int, version_no: int) -> HandoverVersion:
    version = db.scalar(
        select(HandoverVersion).where(HandoverVersion.handover_id == handover_id,
                                      HandoverVersion.version_no == version_no)
    )
    if version is None:
        raise NotFound(f"버전 v{version_no} 을(를) 찾을 수 없습니다.")
    return version


def diff_versions(db: Session, handover_id: int, from_no: int, to_no: int) -> dict[str, Any]:
    left = get_version(db, handover_id, from_no)
    right = get_version(db, handover_id, to_no)
    fields = changed_between(left.after_data, right.after_data)
    return {
        "handover_id": handover_id,
        "from_version": from_no,
        "to_version": to_no,
        "changed_fields": fields,
        "fields": field_diff(left.after_data, right.after_data, fields),
    }


def restore_version(db: Session, handover_id: int, version_no: int, *,
                    expected_version: int, change_reason: str, actor: User,
                    ctx: RequestContext | None = None) -> Handover:
    """v4 를 복원하면 v8 이 새로 생긴다. 기존 버전은 건드리지 않는다(FR-B-05)."""
    if not change_reason or not change_reason.strip():
        raise ValidationFailed("복원 사유는 필수입니다.", detail={"field": "change_reason"})

    handover = get_or_404(db, handover_id, actor, lock=True)
    if handover.is_deleted:
        raise Conflict("삭제된 인수인계는 복원할 수 없습니다. 먼저 복구하십시오.")
    _ensure_editable(handover, actor)

    target = get_version(db, handover_id, version_no)
    if expected_version != handover.current_version_no:
        raise VersionConflict(detail=_conflict_detail(
            db, handover, expected_version, list(VERSIONED_FIELDS), snapshot(handover)))

    before = snapshot(handover)
    for field in VERSIONED_FIELDS:
        if field == "tags":
            continue
        setattr(handover, field, _coerce(field, target.after_data.get(field)))
    _apply_tags(db, handover, list(target.after_data.get("tags") or []))
    db.flush()

    after = snapshot(handover)
    changed = changed_between(before, after)
    if not changed:
        raise Conflict(f"현재 내용이 v{version_no} 과(와) 동일하여 복원할 변경이 없습니다.")

    handover.current_version_no += 1
    handover.updated_by = actor.id
    handover.search_text = build_search_text(db, handover)
    db.flush()

    _add_version(db, handover, change_type=CHANGE_RESTORE,
                 before_data={f: before[f] for f in changed}, after_data=after,
                 changed_fields=changed, change_reason=change_reason.strip(),
                 actor=actor, ctx=ctx, restored_from=version_no)
    reack = ack_service.invalidate_on_change(db, handover, changed)
    record(db, action=actions.HANDOVER_RESTORE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id,
           before={f: before[f] for f in changed}, after={f: after[f] for f in changed},
           detail={"restored_from_version": version_no,
                   "version_no": handover.current_version_no,
                   "reason": change_reason.strip(), "reack_triggered_by": reack})
    return handover


def as_of(db: Session, handover_id: int, at: datetime) -> HandoverVersion | None:
    """지정 시각 기준으로 유효했던 버전(P-07 / §89 '변경 전 내용 재현').

    Windows 의 시계 해상도는 약 15ms 라 한 요청 안에서 만들어진 버전들의 changed_at 이
    같은 값이 될 수 있다. 그때는 "그 시각의 상태"가 더 나중 버전이므로 version_no 로
    결정한다(version_no 는 인수인계별로 단조 증가하므로 시간순과 항상 일치한다).
    """
    return db.scalar(
        select(HandoverVersion)
        .where(HandoverVersion.handover_id == handover_id,
               HandoverVersion.changed_at <= at)
        .order_by(HandoverVersion.version_no.desc())
        .limit(1)
    )


# --------------------------------------------------------------------------- 개인 즐겨찾기

def set_star(db: Session, handover_id: int, user_id: int, starred: bool) -> bool:
    existing = db.get(HandoverStar, {"user_id": user_id, "handover_id": handover_id})
    if starred and existing is None:
        db.add(HandoverStar(user_id=user_id, handover_id=handover_id, created_at=now()))
    elif not starred and existing is not None:
        db.delete(existing)
    db.flush()
    return starred


def is_starred(db: Session, handover_id: int, user_id: int) -> bool:
    return db.get(HandoverStar, {"user_id": user_id, "handover_id": handover_id}) is not None


# --------------------------------------------------------------------------- Timeline

def timeline(db: Session, handover_id: int) -> list[dict[str, Any]]:
    """Version + Ack + Comment 를 시간순으로 합친다(FR-B-07).

    Transfer / Task / Attachment 항목은 해당 Phase 에서 같은 형식으로 덧붙인다.

    시계 해상도 때문에 서로 다른 사건이 같은 시각을 가질 수 있으므로, 동점일 때의 순서를
    _seq 로 고정한다(같은 시각이면 버전 → 확인 → 댓글 순). 화면 순서가 새로고침마다
    달라지는 것을 막는다.
    """
    events: list[dict[str, Any]] = []

    for version in list_versions(db, handover_id):
        events.append({
            "kind": "VERSION",
            "_seq": version.version_no,
            "at": version.changed_at,
            "actor_id": version.changed_by,
            "title": f"v{version.version_no} {version.change_type}",
            "detail": {
                "version_no": version.version_no,
                "change_type": version.change_type,
                "changed_fields": version.changed_fields,
                "change_reason": version.change_reason,
                "restored_from_version": version.restored_from_version,
            },
        })

    for ack in ack_service.list_for_handover(db, handover_id):
        if ack.acked_at is not None:
            events.append({
                "kind": "ACK",
                "_seq": 1_000_000 + ack.id,
                "at": ack.acked_at,
                "actor_id": ack.user_id,
                "title": f"v{ack.acked_version_no} 확인",
                "detail": {"state": ack.state, "acked_version_no": ack.acked_version_no,
                           "note": ack.note},
            })
        if ack.stale_since is not None:
            events.append({
                "kind": "REACK_REQUIRED",
                "_seq": 2_000_000 + ack.id,
                "at": ack.stale_since,
                "actor_id": ack.user_id,
                "title": "재확인 필요로 전환",
                "detail": {"stale_reason": ack.stale_reason},
            })

    comments = db.scalars(
        select(HandoverComment)
        .where(HandoverComment.handover_id == handover_id,
               HandoverComment.is_deleted.is_(False))
    ).all()
    for comment in comments:
        events.append({
            "kind": "COMMENT",
            "_seq": 3_000_000 + comment.id,
            "at": comment.created_at,
            "actor_id": comment.author_id,
            "title": "댓글",
            "detail": {"body": comment.body, "is_edited": comment.is_edited},
        })

    events.sort(key=lambda e: (e["at"], e["_seq"]), reverse=True)
    for event in events:
        event.pop("_seq", None)
    return events
