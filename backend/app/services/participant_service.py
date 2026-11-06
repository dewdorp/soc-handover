"""업무에 걸린 사람들 — 복수 담당 · 필수 인수자 · 참고 전파 · CERT 전체 전파.

세 가지를 지킨다.

1) **사람 id 로 합친다.** 담당으로도 참고로도 들어온 사람은 한 줄만 남는다(강한 역할이
   이긴다). 두 줄이 남으면 확인 숫자가 두 번 세어지고, 받는 사람은 같은 알림을 두 번 받는다.

2) **보내기 전에 몇 명인지 보여 준다.** CERT 전체 전파처럼 범위가 큰 동작은 누르기 전에
   담당 N / 필수 N / 참고 N / 제외 M 을 먼저 보여 준다. 숫자를 보지 않고 누르는 전파는
   '전 직원에게 침해사고 상세가 간' 사고로 끝난다.

3) **공개 범위를 저절로 넓히지 않는다.** 전파는 **사람을 거는 것**이지 글을 여는 것이
   아니다. handovers.visibility 와 공개 그룹은 그대로 둔다. 걸린 사람은 당사자로서
   그 건을 보게 되며, 누가 왜 걸렸는지가 행으로 남는다(그룹을 통째로 여는 것과 다르다).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.context import RequestContext
from app.core.errors import ValidationFailed
from app.models.group import Group, UserGroup
from app.models.handover import Handover
from app.models.participant import (MUST_ACK, PARTICIPANT_ROLES, ROLE_CO_OWNER, ROLE_FYI,
                                    ROLE_LABEL, ROLE_OWNER, ROLE_RANK, ROLE_REQUIRED,
                                    HandoverParticipant)
from app.models.user import User
from app.services.audit_service import record


def list_for(db: Session, handover: Handover) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(HandoverParticipant)
        .where(HandoverParticipant.handover_id == handover.id)
    ).all()
    rows = sorted(rows, key=lambda r: (ROLE_RANK[r.role], r.user.display_name if r.user else ""))
    return [{
        "user_id": r.user_id,
        "display_name": r.user.display_name if r.user else f"#{r.user_id}",
        "username": r.user.username if r.user else "",
        "role": r.role,
        "role_label": ROLE_LABEL[r.role],
        "must_ack": r.role in MUST_ACK,
        "note": r.note,
    } for r in rows]


def counts(db: Session, handover: Handover) -> dict[str, int]:
    rows = db.scalars(select(HandoverParticipant.role)
                      .where(HandoverParticipant.handover_id == handover.id)).all()
    out = {role: 0 for role in PARTICIPANT_ROLES}
    for role in rows:
        out[role] += 1
    return out


def user_ids(db: Session, handover_id: int, roles: tuple[str, ...] | None = None) -> list[int]:
    stmt = select(HandoverParticipant.user_id).where(
        HandoverParticipant.handover_id == handover_id)
    if roles:
        stmt = stmt.where(HandoverParticipant.role.in_(roles))
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- 합치기

def merge(pairs: list[tuple[int, str]]) -> dict[int, str]:
    """(사람, 역할) 목록을 사람 id 로 합친다. 같은 사람이 여럿이면 **강한 역할**을 남긴다."""
    picked: dict[int, str] = {}
    for user_id, role in pairs:
        if role not in ROLE_RANK:
            raise ValidationFailed(f"알 수 없는 역할입니다: {role}",
                                   detail={"allowed": list(PARTICIPANT_ROLES)})
        current = picked.get(user_id)
        if current is None or ROLE_RANK[role] < ROLE_RANK[current]:
            picked[user_id] = role
    return picked


def _validate_users(db: Session, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    found = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    missing = sorted(ids - set(found))
    if missing:
        raise ValidationFailed("존재하지 않는 사용자입니다.",
                               detail={"field": "participants", "ids": missing})
    inactive = sorted(u.username for u in found.values() if not u.is_active)
    if inactive:
        raise ValidationFailed("비활성 계정은 지정할 수 없습니다.", detail={"users": inactive})
    return found


# --------------------------------------------------------------------------- 지정

def set_participants(db: Session, handover: Handover, entries: list[dict[str, Any]], *,
                     actor: User, ctx: RequestContext | None = None,
                     note: str | None = None, replace: bool = True) -> dict[str, Any]:
    """사람들을 통째로 바꾸거나(replace) 더한다.

    대표 담당(OWNER)은 한 명뿐이며 handovers.assignee_id 와 같은 사람으로 맞춘다 — 두 곳이
    어긋나면 목록의 '담당자'와 상세의 '대표 담당'이 서로 다른 이름을 보여 준다.
    """
    from app.services import ack_service

    wanted = merge([(int(e["user_id"]), str(e.get("role") or ROLE_REQUIRED)) for e in entries])
    owners = [uid for uid, role in wanted.items() if role == ROLE_OWNER]
    if len(owners) > 1:
        raise ValidationFailed("대표 담당은 한 명입니다. 나머지는 공동 담당으로 지정하십시오.",
                               detail={"user_ids": sorted(owners)})
    people = _validate_users(db, set(wanted))

    # 감사 payload 는 JSON 이고 키는 문자열이어야 한다 — 사람 id 를 키로 쓰면 기록이 터진다.
    before = _snapshot(list_for(db, handover))
    if replace:
        db.execute(delete(HandoverParticipant).where(
            HandoverParticipant.handover_id == handover.id,
            HandoverParticipant.user_id.notin_(set(wanted) or {0})))
    existing = {p.user_id: p for p in db.scalars(select(HandoverParticipant).where(
        HandoverParticipant.handover_id == handover.id))}

    for uid, role in wanted.items():
        row = existing.get(uid)
        if row is None:
            row = HandoverParticipant(handover_id=handover.id, user_id=uid,
                                      added_by=actor.id)
            db.add(row)
        elif ROLE_RANK[role] >= ROLE_RANK[row.role] and not replace:
            continue        # 더하기 모드에서는 약한 역할로 끌어내리지 않는다
        row.role = role
        if note:
            row.note = note
    db.flush()

    # 대표 담당은 handovers.assignee_id 와 같은 사람으로 맞춘다
    if owners:
        handover.assignee_id = owners[0]
    db.flush()

    # 확인 의무가 있는 사람에게는 미확인을 만든다. 참고(FYI)는 만들지 않는다.
    for uid, role in wanted.items():
        if role in MUST_ACK and uid != actor.id:
            ack_service.mark_pending(db, handover, uid)
    _notify(db, handover, wanted, actor, note=note)

    after = _snapshot(list_for(db, handover))
    if before != after:
        record(db, action=actions.HANDOVER_PARTICIPANTS, ctx=ctx, user=actor,
               resource_type="HANDOVER", resource_id=handover.id,
               before={"participants": before}, after={"participants": after})
    return {"participants": list_for(db, handover), "counts": counts(db, handover),
            "names": {uid: people[uid].display_name for uid in wanted}}


def _snapshot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """감사에 남길 모양 — 누가 어느 역할이었는지 사람이 읽을 수 있게."""
    return [{"user_id": r["user_id"], "name": r["display_name"], "role": r["role"]}
            for r in rows]


def _notify(db: Session, handover: Handover, wanted: dict[int, str], actor: User,
            *, note: str | None) -> None:
    from app.services import notification_service as ns

    for uid, role in wanted.items():
        if uid == actor.id:
            continue
        label = ROLE_LABEL[role]
        body = f"{actor.display_name} 님이 {label}(으)로 지정"
        if note:
            body = f"{body} · {note}"
        ns.notify_once(db, user_id=uid, type_=ns.T_ASSIGNED,
                       title=f"{label}: {handover.title}", body=body,
                       link_type="HANDOVER", link_id=handover.id,
                       dedup_key=f"participant:{handover.id}:{uid}:{role}")


# --------------------------------------------------------------------------- 전파

def _group_members(db: Session, group_ids: list[int]) -> dict[int, list[str]]:
    """그룹별 구성원(활성 계정만). 미리보기에 '어느 그룹에서 몇 명'을 적기 위해 이름도 같이."""
    if not group_ids:
        return {}
    rows = db.execute(
        select(UserGroup.group_id, User.id, User.display_name)
        .join(User, User.id == UserGroup.user_id)
        .join(Group, Group.id == UserGroup.group_id)
        .where(UserGroup.group_id.in_(group_ids), Group.is_active.is_(True),
               User.is_active.is_(True))).all()
    out: dict[int, list[str]] = {}
    for gid, uid, name in rows:
        out.setdefault(gid, []).append((uid, name))
    return out


def propagate_preview(db: Session, handover: Handover, *, group_ids: list[int],
                      role: str = ROLE_FYI, exclude_user_ids: list[int] | None = None,
                      actor: User) -> dict[str, Any]:
    """전파하면 누가 몇 명 걸리는지 — **누르기 전에** 보여 준다.

    제외(M)에는 두 종류가 들어간다: 손으로 뺀 사람, 그리고 이미 더 강한 역할로 걸려 있어
    바뀌지 않는 사람. 둘을 구분해서 보여 줘야 '왜 10명인데 7명만 갔지'가 생기지 않는다.
    """
    if role not in PARTICIPANT_ROLES:
        raise ValidationFailed("알 수 없는 역할입니다.", detail={"allowed": list(PARTICIPANT_ROLES)})
    excluded = set(exclude_user_ids or [])
    members = _group_members(db, group_ids)
    found_groups = {g.id: g.name for g in db.scalars(
        select(Group).where(Group.id.in_(group_ids or [0])))}
    missing = sorted(set(group_ids) - set(found_groups))
    if missing:
        raise ValidationFailed("존재하지 않는 그룹입니다.",
                               detail={"field": "group_ids", "ids": missing})

    current = {p.user_id: p.role for p in db.scalars(select(HandoverParticipant).where(
        HandoverParticipant.handover_id == handover.id))}

    will_add: dict[int, str] = {}
    skipped_excluded: list[str] = []
    skipped_stronger: list[str] = []
    for gid, people in members.items():
        for uid, name in people:
            if uid in excluded:
                skipped_excluded.append(name)
                continue
            have = current.get(uid)
            if have is not None and ROLE_RANK[have] <= ROLE_RANK[role]:
                skipped_stronger.append(f"{name}({ROLE_LABEL[have]})")
                continue
            will_add[uid] = role

    after = dict(current)
    after.update(will_add)
    by_role = {r: 0 for r in PARTICIPANT_ROLES}
    for r in after.values():
        by_role[r] += 1

    return {
        "groups": [{"id": gid, "name": found_groups[gid],
                    "member_count": len(members.get(gid, []))} for gid in group_ids],
        "role": role,
        "role_label": ROLE_LABEL[role],
        "add_count": len(will_add),
        "add_user_ids": sorted(will_add),
        "excluded_count": len(set(skipped_excluded)) + len(set(skipped_stronger)),
        "excluded_by_hand": sorted(set(skipped_excluded)),
        "excluded_already_stronger": sorted(set(skipped_stronger)),
        "after": {
            "owner": by_role[ROLE_OWNER],
            "co_owner": by_role[ROLE_CO_OWNER],
            "required": by_role[ROLE_REQUIRED],
            "fyi": by_role[ROLE_FYI],
            "total": sum(by_role.values()),
            "must_ack": by_role[ROLE_OWNER] + by_role[ROLE_CO_OWNER] + by_role[ROLE_REQUIRED],
        },
        #: 전파는 공개 범위를 바꾸지 않는다 — 화면이 이 문구를 그대로 보여 준다.
        "visibility_note": ("전파는 사람을 거는 것입니다. 글의 공개 범위"
                            f"(현재 {handover.visibility})는 바뀌지 않습니다."),
        #: 그룹 제한 글을 그 그룹 밖으로 전파할 때의 경고(§3). 막지는 않는다 —
        #: 받는 사람이 일을 해야 전파하는 것이므로. 다만 누르기 전에 알아야 한다.
        "outside_scope": _outside_scope_warning(db, handover, group_ids, found_groups),
    }


def _outside_scope_warning(db: Session, handover: Handover, group_ids: list[int],
                           found_groups: dict[int, str]) -> dict[str, Any] | None:
    """이 전파가 '그룹 제한을 그 그룹 밖으로' 넓히는지 — 넓힌다면 무엇을 누구에게인지."""
    from app.models.group import VIS_GROUPS
    from app.services import group_service

    if handover.visibility != VIS_GROUPS:
        return None
    allowed = set(group_service.group_ids_of(handover))
    outside = [gid for gid in group_ids if gid not in allowed]
    if not outside:
        return None
    scope_names = group_service.group_names_of(db, handover)
    outside_names = [found_groups[gid] for gid in outside if gid in found_groups]
    return {
        "scope_groups": scope_names,
        "outside_groups": outside_names,
        "message": (f"이 글은 {' · '.join(scope_names)}에만 공개돼 있습니다. "
                    f"전파하면 {' · '.join(outside_names)} 구성원도 이 글을 읽게 됩니다"
                    " — 글의 공개 범위는 그대로이고, 그 사람들에게만 열립니다."),
    }


def propagate(db: Session, handover: Handover, *, group_ids: list[int], role: str = ROLE_FYI,
              exclude_user_ids: list[int] | None = None, note: str | None,
              actor: User, ctx: RequestContext | None = None) -> dict[str, Any]:
    """미리보기와 **같은 계산**으로 실제로 건다. 공개 범위는 손대지 않는다."""
    preview = propagate_preview(db, handover, group_ids=group_ids, role=role,
                                exclude_user_ids=exclude_user_ids, actor=actor)
    if preview["add_user_ids"]:
        label = note or ("전파: " + " · ".join(g["name"] for g in preview["groups"]))
        set_participants(db, handover,
                         [{"user_id": uid, "role": role} for uid in preview["add_user_ids"]],
                         actor=actor, ctx=ctx, note=label, replace=False)
    after = {"groups": [g["name"] for g in preview["groups"]],
             "role": role, "added": preview["add_count"],
             "excluded": preview["excluded_count"],
             "visibility": handover.visibility}
    if preview.get("outside_scope"):
        # 조사하는 사람이 '그룹 제한 글이 그 그룹 밖으로 나갔다'를 기록만 보고 알 수 있게
        # 남긴다. 나중에 재구성하려면 그때의 공개 그룹을 따로 찾아야 한다.
        after["outside_scope_groups"] = preview["outside_scope"]["outside_groups"]
        after["scope_groups"] = preview["outside_scope"]["scope_groups"]
    record(db, action=actions.HANDOVER_PROPAGATE, ctx=ctx, user=actor,
           resource_type="HANDOVER", resource_id=handover.id, after=after)
    return {**preview, "applied": True,
            "participants": list_for(db, handover)}
