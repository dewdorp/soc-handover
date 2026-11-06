"""열람 그룹 — 판정 한 곳, 관리 한 곳.

이 모듈에는 두 가지가 들어 있다.

1) **열람 판정**(visible_clause / assert_visible)
   목록·건수·패싯·상세·첨부·댓글·이력·검색·알림·통계·Excel 이 전부 이 두 함수를 지난다.
   역할(ADMIN/MANAGER)은 판정에 들어가지 않는다 — 그룹을 관리할 수 있다는 것이
   다른 그룹 업무의 원문을 읽을 근거는 아니다(§3).

   볼 수 있는 조건은 OR 네 가지다.
     · 전체 공개(visibility=ALL)로 쓴 글
     · 내가 속한 **활성** 그룹에 공개된 글
     · 내가 쓴 글 · 보낸 글 · 담당자 · 확인자인 글
     · 교대 인계로 나에게 온 글(수신자)
   마지막 두 개가 없으면, 그룹이 바뀐 순간 내 업무가 내 화면에서 사라진다.

2) **그룹 관리**(만들기 · 이름 바꾸기 · 비활성 · 구성원)
   비활성 그룹은 즉시 판정에서 빠진다 — 멤버십을 지우지 않아도 열람이 끊긴다.
   멤버십 변경은 DB 를 보고 판정하므로 **다음 요청부터 곧바로** 적용된다(캐시 없음).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, exists, false, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.audit import actions
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.group import (GROUP_UNCLASSIFIED, VIS_ALL, VIS_GROUPS, VISIBILITIES,
                              Group, HandoverGroup, UserGroup)
from app.models.handover import Handover
from app.models.participant import HandoverParticipant
from app.models.shift import ShiftHandoverItem, ShiftHandoverRecipient
from app.models.user import User
from app.services.audit_service import record


# --------------------------------------------------------------------------- 예약 그룹

def ensure_unclassified(db: Session, name: str = "미분류") -> Group:
    """이관 전 자료가 모이는 그룹. **코드로 찾는다**(현장에서 이름을 바꿔 쓸 수 있다)."""
    group = db.scalar(select(Group).where(Group.code == GROUP_UNCLASSIFIED))
    if group is not None:
        return group
    by_name = db.scalar(select(Group).where(Group.name == name))
    if by_name is not None:
        if by_name.code is None:
            by_name.code = GROUP_UNCLASSIFIED
            db.flush()
        return by_name
    group = Group(code=GROUP_UNCLASSIFIED, name=name,
                  description="그룹이 정해지지 않은 자료. 관리자가 옮기기 전까지 이 그룹만 본다.",
                  sort_order=999)
    db.add(group)
    db.flush()
    return group


# --------------------------------------------------------------------------- 내 그룹

def my_group_ids(db: Session, user_id: int) -> tuple[int, ...]:
    """내가 속한 **활성** 그룹 id. 비활성 그룹은 빠진다."""
    rows = db.scalars(
        select(UserGroup.group_id)
        .join(Group, Group.id == UserGroup.group_id)
        .where(UserGroup.user_id == user_id, Group.is_active.is_(True))
    ).all()
    return tuple(sorted(rows))


def my_groups(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Group, UserGroup.is_default)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id, Group.is_active.is_(True))
        .order_by(UserGroup.is_default.desc(), Group.sort_order, Group.name)
    ).all()
    return [{"id": g.id, "name": g.name, "code": g.code, "is_default": bool(d)}
            for g, d in rows]


def default_group_id(db: Session, user_id: int) -> int | None:
    """새 업무의 기본 공개 그룹. 기본 지정이 없으면 속한 그룹 중 첫 번째."""
    gid = db.scalar(
        select(UserGroup.group_id)
        .join(Group, Group.id == UserGroup.group_id)
        .where(UserGroup.user_id == user_id, UserGroup.is_default.is_(True),
               Group.is_active.is_(True))
    )
    if gid is not None:
        return gid
    ids = my_group_ids(db, user_id)
    return ids[0] if ids else None


# --------------------------------------------------------------------------- 판정

def visible_clause(db: Session, user_id: int) -> ColumnElement[bool]:
    """Handover 에 붙이는 열람 조건. 질의를 만드는 모든 자리가 이것을 쓴다."""
    group_ids = my_group_ids(db, user_id)

    terms: list[ColumnElement[bool]] = [Handover.visibility == VIS_ALL]

    if group_ids:
        terms.append(
            exists(
                select(HandoverGroup.id).where(
                    HandoverGroup.handover_id == Handover.id,
                    HandoverGroup.group_id.in_(group_ids),
                ).correlate(Handover)
            )
        )

    # 내가 당사자인 건은 그룹과 무관하게 보인다 — 아니면 내 담당 업무가 내 화면에서 사라진다.
    terms.append(or_(Handover.created_by == user_id,
                     Handover.sender_id == user_id,
                     Handover.assignee_id == user_id,
                     Handover.checker_id == user_id))

    # 공동 담당 · 필수 인수자 · 참고로 걸린 사람(§5). 전파는 글의 공개 범위를 넓히지 않고
    # **사람을 건다** — 그래서 그룹이 아니라 여기로 들어온다.
    terms.append(
        exists(
            select(HandoverParticipant.id).where(
                HandoverParticipant.handover_id == Handover.id,
                HandoverParticipant.user_id == user_id,
            ).correlate(Handover)
        )
    )

    # 교대 인계로 나에게 온 건
    terms.append(
        exists(
            select(ShiftHandoverItem.id)
            .join(ShiftHandoverRecipient,
                  ShiftHandoverRecipient.session_id == ShiftHandoverItem.session_id)
            .where(ShiftHandoverItem.handover_id == Handover.id,
                   ShiftHandoverRecipient.user_id == user_id)
            .correlate(Handover)
        )
    )
    return or_(*terms)


def can_see(db: Session, handover: Handover, user: User) -> bool:
    """이미 읽어 온 행 하나에 대한 판정. 같은 규칙을 파이썬에서 다시 쓰지 않도록 DB 에 묻는다."""
    return bool(db.scalar(
        select(func.count()).select_from(Handover)
        .where(Handover.id == handover.id, visible_clause(db, user.id))
    ))


def assert_visible(db: Session, handover: Handover, user: User) -> None:
    """볼 수 없으면 **404**. 403 이면 '그런 번호의 업무가 있다'는 사실이 새어 나간다."""
    if not can_see(db, handover, user):
        raise NotFound("인수인계를 찾을 수 없습니다.")


# --------------------------------------------------------------------------- 업무의 공개 범위

def group_ids_of(handover: Handover) -> list[int]:
    return sorted(link.group_id for link in handover.group_links)


def group_names_of(db: Session, handover: Handover) -> list[str]:
    ids = group_ids_of(handover)
    if not ids:
        return []
    rows = db.scalars(select(Group.name).where(Group.id.in_(ids)).order_by(Group.name)).all()
    return list(rows)


def apply_scope(db: Session, handover: Handover, *, visibility: str | None,
                group_ids: list[int] | None, actor: User) -> None:
    """공개 범위 변경. 그룹 미지정은 전체 공개, 그룹 지정 시 명시 그룹만.

    보안 규칙:
    - visibility=ALL 은 이전 그룹 연결을 제거한다.
    - group_ids 가 비어 있지 않으면 GROUPS 를 암시한다(기존 API 호환).
    - 명시적인 GROUPS 인데 지정 그룹이 없으면 거절한다(실수로 전체 공개 방지).
    - 수정 요청에서 visibility/group_ids 모두 생략하면 기존 범위를 그대로 둔다.
    - 남의 그룹에는 게시할 수 없다.
    """
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValidationFailed("공개 범위 값이 올바르지 않습니다.",
                               detail={"field": "visibility", "allowed": list(VISIBILITIES)})

    if visibility == VIS_ALL:
        handover.visibility = VIS_ALL
    elif visibility == VIS_GROUPS:
        handover.visibility = VIS_GROUPS
    elif group_ids is not None:
        handover.visibility = VIS_GROUPS if group_ids else VIS_ALL

    if handover.visibility == VIS_ALL:
        handover.group_links.clear()
        db.flush()
        return

    if group_ids is not None:
        wanted = {int(g) for g in group_ids}
    else:
        wanted = set(group_ids_of(handover))
    if not wanted:
        raise ValidationFailed("그룹 공개를 선택한 경우 공개할 그룹을 하나 이상 지정하십시오.",
                               detail={"field": "group_ids"})

    found = set(db.scalars(select(Group.id)
                           .where(Group.id.in_(wanted), Group.is_active.is_(True))).all())
    missing = wanted - found
    if missing:
        raise ValidationFailed("존재하지 않거나 사용하지 않는 그룹입니다.",
                               detail={"field": "group_ids", "ids": sorted(missing)})
    mine = set(my_group_ids(db, actor.id))
    outside = wanted - mine
    if outside:
        names = db.scalars(select(Group.name).where(Group.id.in_(outside))).all()
        raise ValidationFailed("내가 속하지 않은 그룹에는 공개할 수 없습니다.",
                               detail={"field": "group_ids", "groups": sorted(names)})

    current = {link.group_id: link for link in list(handover.group_links)}
    for gid, link in current.items():
        if gid not in wanted:
            handover.group_links.remove(link)
    for gid in sorted(wanted - set(current)):
        handover.group_links.append(HandoverGroup(handover_id=handover.id, group_id=gid))
    db.flush()


# --------------------------------------------------------------------------- 관리 (관리자)

def list_groups(db: Session, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    stmt = select(Group).order_by(Group.sort_order, Group.name)
    if not include_inactive:
        stmt = stmt.where(Group.is_active.is_(True))
    out: list[dict[str, Any]] = []
    for g in db.scalars(stmt):
        out.append({
            "id": g.id, "code": g.code, "name": g.name, "description": g.description,
            "is_active": g.is_active, "sort_order": g.sort_order,
            "member_count": db.scalar(select(func.count()).select_from(UserGroup)
                                      .where(UserGroup.group_id == g.id)) or 0,
            "handover_count": db.scalar(select(func.count()).select_from(HandoverGroup)
                                        .join(Handover, Handover.id == HandoverGroup.handover_id)
                                        .where(HandoverGroup.group_id == g.id,
                                               Handover.is_deleted == false())) or 0,
        })
    return out


def get_or_404(db: Session, group_id: int) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise NotFound("그룹을 찾을 수 없습니다.")
    return group


def create_group(db: Session, *, name: str, description: str | None = None,
                 sort_order: int = 0, actor: User,
                 ctx: RequestContext | None = None) -> Group:
    clean = (name or "").strip()
    if not clean:
        raise ValidationFailed("그룹 이름을 입력하십시오.", detail={"field": "name"})
    if db.scalar(select(Group).where(Group.name == clean)) is not None:
        raise Conflict("같은 이름의 그룹이 이미 있습니다.", detail={"field": "name"})
    group = Group(name=clean, description=description, sort_order=sort_order, is_active=True)
    db.add(group)
    db.flush()
    record(db, action=actions.GROUP_CREATE, ctx=ctx, user=actor,
           resource_type="GROUP", resource_id=group.id, after={"name": clean})
    return group


def update_group(db: Session, group_id: int, changes: dict[str, Any], *, actor: User,
                 ctx: RequestContext | None = None) -> Group:
    group = get_or_404(db, group_id)
    before = {"name": group.name, "is_active": group.is_active,
              "description": group.description, "sort_order": group.sort_order}

    if changes.get("name") is not None:
        clean = str(changes["name"]).strip()
        if not clean:
            raise ValidationFailed("그룹 이름을 입력하십시오.", detail={"field": "name"})
        dup = db.scalar(select(Group).where(Group.name == clean, Group.id != group.id))
        if dup is not None:
            raise Conflict("같은 이름의 그룹이 이미 있습니다.", detail={"field": "name"})
        group.name = clean
    for field in ("description", "sort_order"):
        if changes.get(field) is not None:
            setattr(group, field, changes[field])
    if changes.get("is_active") is not None:
        if not changes["is_active"] and group.code == GROUP_UNCLASSIFIED:
            raise ValidationFailed("'미분류' 그룹은 사용 중지할 수 없습니다. "
                                   "자료를 다른 그룹으로 옮긴 뒤 비우십시오.")
        group.is_active = bool(changes["is_active"])
    db.flush()

    after = {"name": group.name, "is_active": group.is_active,
             "description": group.description, "sort_order": group.sort_order}
    record(db, action=actions.GROUP_UPDATE, ctx=ctx, user=actor,
           resource_type="GROUP", resource_id=group.id, before=before, after=after)
    return group


def members(db: Session, group_id: int) -> list[dict[str, Any]]:
    get_or_404(db, group_id)
    rows = db.execute(
        select(User, UserGroup.is_default)
        .join(UserGroup, UserGroup.user_id == User.id)
        .where(UserGroup.group_id == group_id)
        .order_by(User.display_name)
    ).all()
    return [{"user_id": u.id, "username": u.username, "display_name": u.display_name,
             "role_code": u.role_code, "is_active": u.is_active, "is_default": bool(d)}
            for u, d in rows]


def set_memberships(db: Session, user_id: int, group_ids: list[int],
                    default_group: int | None, *, actor: User,
                    ctx: RequestContext | None = None) -> list[dict[str, Any]]:
    """한 사람의 그룹 소속을 통째로 바꾼다. 다음 요청부터 곧바로 적용된다."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")
    wanted = {int(g) for g in group_ids}
    if wanted:
        found = set(db.scalars(select(Group.id).where(Group.id.in_(wanted))).all())
        missing = wanted - found
        if missing:
            raise ValidationFailed("존재하지 않는 그룹입니다.",
                                   detail={"field": "group_ids", "ids": sorted(missing)})
    if default_group is not None and default_group not in wanted:
        raise ValidationFailed("기본 그룹은 소속 그룹 중에서 고르십시오.",
                               detail={"field": "default_group_id"})

    before = sorted(db.scalars(select(UserGroup.group_id)
                               .where(UserGroup.user_id == user_id)).all())
    db.execute(delete(UserGroup).where(UserGroup.user_id == user_id,
                                       UserGroup.group_id.notin_(wanted or {0})))
    existing = {ug.group_id: ug for ug in db.scalars(
        select(UserGroup).where(UserGroup.user_id == user_id))}
    for gid in sorted(wanted):
        ug = existing.get(gid)
        if ug is None:
            ug = UserGroup(user_id=user_id, group_id=gid)
            db.add(ug)
        ug.is_default = (gid == default_group)
    db.flush()

    record(db, action=actions.GROUP_MEMBER_CHANGE, ctx=ctx, user=actor,
           resource_type="USER", resource_id=user_id,
           before={"group_ids": before},
           after={"group_ids": sorted(wanted), "default_group_id": default_group})
    return my_groups(db, user_id)


# --------------------------------------------------------------------------- 자료 이관

def move_unclassified(db: Session, *, to_group_id: int, company_id: int | None = None,
                      limit: int | None = None, actor: User,
                      ctx: RequestContext | None = None) -> dict[str, Any]:
    """'미분류'에 남은 업무를 지정한 그룹으로 옮긴다(관리자 이관 도구).

    전체 공개로 바꾸지 않는다 — 그룹만 바꾼다. 관계사별로 나눠 여러 번 돌릴 수 있다.
    """
    target = get_or_404(db, to_group_id)
    if not target.is_active:
        raise ValidationFailed("사용 중지된 그룹으로는 옮길 수 없습니다.")
    unclassified = ensure_unclassified(db)
    if target.id == unclassified.id:
        raise ValidationFailed("'미분류'에서 '미분류'로는 옮길 수 없습니다.")

    stmt = (select(Handover.id)
            .join(HandoverGroup, HandoverGroup.handover_id == Handover.id)
            .where(HandoverGroup.group_id == unclassified.id)
            .order_by(Handover.id))
    if company_id is not None:
        stmt = stmt.where(Handover.company_id == company_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    ids = list(db.scalars(stmt))

    moved = 0
    for hid in ids:
        db.execute(delete(HandoverGroup).where(HandoverGroup.handover_id == hid,
                                               HandoverGroup.group_id == unclassified.id))
        already = db.scalar(select(HandoverGroup.id)
                            .where(HandoverGroup.handover_id == hid,
                                   HandoverGroup.group_id == target.id))
        if already is None:
            db.add(HandoverGroup(handover_id=hid, group_id=target.id))
        moved += 1
    db.flush()

    remaining = db.scalar(
        select(func.count()).select_from(HandoverGroup)
        .where(HandoverGroup.group_id == unclassified.id)) or 0
    record(db, action=actions.GROUP_DATA_MOVE, ctx=ctx, user=actor,
           resource_type="GROUP", resource_id=target.id,
           after={"moved": moved, "company_id": company_id, "remaining": remaining})
    return {"moved": moved, "remaining": remaining, "to_group_id": target.id}


def unclassified_summary(db: Session) -> dict[str, Any]:
    """이관 화면이 보여 줄 '아직 미분류로 남은 것' 집계."""
    from app.models.reference import Company

    unclassified = ensure_unclassified(db)
    rows = db.execute(
        select(Company.id, Company.name, func.count(Handover.id))
        .select_from(HandoverGroup)
        .join(Handover, and_(Handover.id == HandoverGroup.handover_id,
                             Handover.is_deleted == false()))
        .join(Company, Company.id == Handover.company_id)
        .where(HandoverGroup.group_id == unclassified.id)
        .group_by(Company.id, Company.name)
        .order_by(func.count(Handover.id).desc())
    ).all()
    return {
        "group_id": unclassified.id,
        "group_name": unclassified.name,
        "total": sum(c for _, _, c in rows),
        "by_company": [{"company_id": i, "company_name": n, "count": c} for i, n, c in rows],
    }
