"""근무표 — 계획(주기 계산) + 실제(예외 반영).

핵심 구분
  · **계획 근무자**  조 편성과 16일 주기만으로 나오는 사람. 달력의 밑그림이다.
  · **실제 근무자**  거기에 대근 · 맞교환 · 결원을 얹은 사람. 인계 상대를 고르는 기준은
    언제나 이쪽이다 — 대근자가 들어왔는데 계획표의 사람에게 인계하면 그 인계는 비게 된다.

야간은 **시작 날짜**로 센다. 11/05 야간은 11/05 18:00 ~ 11/06 09:00 이다. 자정을 넘는
근무를 '끝난 날'로 적으면 09:00 에 교대하는 사람이 전날 날짜를 찾아야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, null, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.time import KST, now, today
from app.models.roster import (CYCLE_DAYS, OVR_OFF, OVR_SUB, OVR_SWAP, PATTERN, SHIFT_DAY,
                               SHIFT_NIGHT, SHIFT_OFF, RosterMember, RosterOverride,
                               RosterTeam)
from app.models.user import User
from app.services import settings_service
from app.services.audit_service import record

#: 기준일 설정 키 — 이 날짜에 phase_days=0 인 조가 주기의 첫날(주간 1일째)에 있다.
EPOCH_KEY = "roster.epoch_date"
DEFAULT_EPOCH = "2026-01-05"      # 월요일

#: 한 조의 정원. 이보다 적게 서면 '결원'으로 표시한다.
TEAM_SIZE_KEY = "roster.team_size"
DEFAULT_TEAM_SIZE = 4

SHIFT_TIMES = {SHIFT_DAY: (time(9, 0), time(18, 0)),
               SHIFT_NIGHT: (time(18, 0), time(9, 0))}
SHIFT_LABEL = {SHIFT_DAY: "주간", SHIFT_NIGHT: "야간", SHIFT_OFF: "비번"}

_LETTER = {"D": SHIFT_DAY, "N": SHIFT_NIGHT, ".": SHIFT_OFF}


# --------------------------------------------------------------------------- 주기 계산

@dataclass(frozen=True, slots=True)
class Plan:
    """한 요청 동안 바뀌지 않는 것들 — 기준일 · 조 편성 · 정원.

    월 보기 한 번에 이 셋을 수백 번 다시 읽던 것을 한 번으로 줄인다.
    """
    epoch: date
    teams: tuple[RosterTeam, ...]
    size: int


def plan(db: Session) -> Plan:
    return Plan(epoch=epoch(db), teams=tuple(teams(db)), size=team_size(db))


def epoch(db: Session) -> date:
    raw = settings_service.get_value(db, EPOCH_KEY) or DEFAULT_EPOCH
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return date.fromisoformat(DEFAULT_EPOCH)


def team_size(db: Session) -> int:
    value = settings_service.get_value(db, TEAM_SIZE_KEY)
    return int(value) if isinstance(value, int) and value > 0 else DEFAULT_TEAM_SIZE


def phase_index(db: Session, team: RosterTeam, day: date, *, at: Plan | None = None) -> int:
    """그 날 이 조가 주기의 몇 번째 날인가(0..15)."""
    base = (at or plan(db)).epoch
    return (day - base).days - team.phase_days


def shift_of(db: Session, team: RosterTeam, day: date, *, at: Plan | None = None) -> str:
    return _LETTER[PATTERN[phase_index(db, team, day, at=at) % CYCLE_DAYS]]


def teams(db: Session, *, include_inactive: bool = False) -> list[RosterTeam]:
    stmt = select(RosterTeam).order_by(RosterTeam.sort_order, RosterTeam.code)
    if not include_inactive:
        stmt = stmt.where(RosterTeam.is_active.is_(True))
    return list(db.scalars(stmt))


def team_on(db: Session, day: date, shift_code: str, *,
            at: Plan | None = None) -> RosterTeam | None:
    """그 날 그 교대를 서는 조. 주기가 맞물려 있으면 하나뿐이다."""
    at = at or plan(db)
    for team in at.teams:
        if shift_of(db, team, day, at=at) == shift_code:
            return team
    return None


# --------------------------------------------------------------------------- 계획 · 실제

def _overrides(db: Session, day: date, shift_code: str) -> list[RosterOverride]:
    return list(db.scalars(
        select(RosterOverride)
        .where(RosterOverride.work_date == day,
               RosterOverride.shift_code == shift_code,
               RosterOverride.canceled_at.is_(null()))
        .order_by(RosterOverride.id)))


def planned_user_ids(db: Session, day: date, shift_code: str, *,
                     at: Plan | None = None) -> list[int]:
    team = team_on(db, day, shift_code, at=at)
    if team is None:
        return []
    return [m.user_id for m in team.members]


def staffing(db: Session, day: date, shift_code: str, *,
             at: Plan | None = None) -> dict[str, Any]:
    """그 날 그 교대의 계획 · 실제 · 결원. 화면과 인계 추천이 같은 함수를 쓴다.

    at 을 주면 기준일 · 조 편성 · 정원을 다시 읽지 않는다(달력이 하루씩 부를 때).
    """
    at = at or plan(db)
    team = team_on(db, day, shift_code, at=at)
    planned = planned_user_ids(db, day, shift_code, at=at)
    actual = list(planned)
    changes: list[dict[str, Any]] = []

    for ovr in _overrides(db, day, shift_code):
        if ovr.off_user_id in actual:
            actual.remove(ovr.off_user_id)
        if ovr.on_user_id is not None and ovr.on_user_id not in actual:
            actual.append(ovr.on_user_id)
        changes.append({
            "id": ovr.id, "kind": ovr.kind,
            "off_user_id": ovr.off_user_id,
            "off_user_name": ovr.off_user.display_name if ovr.off_user else None,
            "on_user_id": ovr.on_user_id,
            "on_user_name": ovr.on_user.display_name if ovr.on_user else None,
            "reason": ovr.reason,
        })

    size = at.size
    names = _names(db, actual)
    return {
        "work_date": day,
        "shift_code": shift_code,
        "shift_label": SHIFT_LABEL.get(shift_code, shift_code),
        "team_id": team.id if team else None,
        "team_code": team.code if team else None,
        "team_name": team.name if team else None,
        "planned_user_ids": planned,
        "planned_names": _names(db, planned),
        "actual_user_ids": actual,
        "actual_names": names,
        "changes": changes,
        "expected": size,
        "short_by": max(0, size - len(actual)),
        "is_short": len(actual) < size,
    }


def _names(db: Session, user_ids: list[int]) -> list[str]:
    if not user_ids:
        return []
    rows = {u.id: u.display_name for u in db.scalars(
        select(User).where(User.id.in_(user_ids)))}
    return [rows.get(uid, f"#{uid}") for uid in user_ids]


def window_bounds(day: date, shift_code: str) -> tuple[datetime, datetime]:
    """그 근무의 시작 · 끝 시각. 야간은 다음 날 아침에 끝난다."""
    start_t, end_t = SHIFT_TIMES[shift_code]
    start = datetime.combine(day, start_t, tzinfo=KST)
    end_day = day + timedelta(days=1) if shift_code == SHIFT_NIGHT else day
    return start, datetime.combine(end_day, end_t, tzinfo=KST)


# --------------------------------------------------------------------------- 달력

def calendar(db: Session, start: date, end: date, *, actor: User | None = None,
             mine: bool = False) -> dict[str, Any]:
    """주 · 월 공통. 하루에 주간 · 야간 두 줄이 나온다."""
    if end < start:
        raise ValidationFailed("기간의 끝이 시작보다 빠를 수 없습니다.")
    if (end - start).days > 92:
        raise ValidationFailed("근무표는 한 번에 93일까지 볼 수 있습니다.")

    at = plan(db)
    my_id = actor.id if actor else None
    days: list[dict[str, Any]] = []
    day = start
    while day <= end:
        shifts = []
        for code in (SHIFT_DAY, SHIFT_NIGHT):
            row = staffing(db, day, code, at=at)
            row["is_mine"] = my_id in row["actual_user_ids"] if my_id else False
            row["was_mine_planned"] = my_id in row["planned_user_ids"] if my_id else False
            if not mine or row["is_mine"] or row["was_mine_planned"]:
                shifts.append(row)
        off = [t for t in at.teams if shift_of(db, t, day, at=at) == SHIFT_OFF]
        days.append({"day": day, "shifts": shifts,
                     "off_team_codes": [t.code for t in off]})
        day += timedelta(days=1)
    return {"start": start, "end": end, "days": days,
            "cycle_days": CYCLE_DAYS, "pattern": PATTERN, "epoch": at.epoch}


def my_upcoming(db: Session, actor: User, *, days: int = 14) -> list[dict[str, Any]]:
    """'내 근무' — 오늘부터 N일. 대근으로 들어온 근무도 포함한다."""
    out: list[dict[str, Any]] = []
    at = plan(db)
    t0 = today()
    for offset in range(days):
        day = t0 + timedelta(days=offset)
        for code in (SHIFT_DAY, SHIFT_NIGHT):
            row = staffing(db, day, code, at=at)
            if actor.id in row["actual_user_ids"]:
                start, end = window_bounds(day, code)
                out.append({"work_date": day, "shift_code": code,
                            "shift_label": row["shift_label"],
                            "team_code": row["team_code"], "start_at": start, "end_at": end,
                            "with_names": [n for n, uid in zip(row["actual_names"],
                                                               row["actual_user_ids"])
                                           if uid != actor.id],
                            "is_short": row["is_short"], "short_by": row["short_by"]})
    return out


# --------------------------------------------------------------------------- 인계 상대 추천

def current_window(db: Session, at: datetime | None = None) -> tuple[date, str]:
    """지금이 어느 근무인가. 09:00~18:00 은 그 날 주간, 그 밖은 야간(자정 전후로 날짜가 다르다)."""
    at = at or now()
    local = at.astimezone(KST)
    if time(9, 0) <= local.time() < time(18, 0):
        return local.date(), SHIFT_DAY
    if local.time() >= time(18, 0):
        return local.date(), SHIFT_NIGHT
    return local.date() - timedelta(days=1), SHIFT_NIGHT   # 자정~09:00 은 전날 야간


def next_window(db: Session, at: datetime | None = None) -> tuple[date, str]:
    day, code = current_window(db, at)
    if code == SHIFT_DAY:
        return day, SHIFT_NIGHT
    return day + timedelta(days=1), SHIFT_DAY


def suggested_recipients(db: Session, at: datetime | None = None) -> dict[str, Any]:
    """다음 근무의 **실제** 근무자. 교대 인계 화면이 인수자를 미리 채우는 데 쓴다.

    계획표가 아니라 실제를 쓴다 — 대근이 들어왔으면 대근자에게 넘겨야 한다.
    """
    day, code = next_window(db, at)
    row = staffing(db, day, code)
    return {
        "work_date": day, "shift_code": code, "shift_label": row["shift_label"],
        "team_code": row["team_code"], "team_name": row["team_name"],
        "user_ids": row["actual_user_ids"], "names": row["actual_names"],
        "is_short": row["is_short"], "short_by": row["short_by"],
        "replaced": [c for c in row["changes"] if c["kind"] != OVR_OFF],
    }


# --------------------------------------------------------------------------- 조 편성

def get_team_or_404(db: Session, team_id: int) -> RosterTeam:
    team = db.get(RosterTeam, team_id)
    if team is None:
        raise NotFound("근무조를 찾을 수 없습니다.")
    return team


def set_members(db: Session, team_id: int, user_ids: list[int], *, leader_id: int | None,
                actor: User, ctx: RequestContext | None = None) -> RosterTeam:
    """조 편성을 통째로 바꾼다. **한 사람이 두 조에 들어가는 것은 막는다**."""
    team = get_team_or_404(db, team_id)
    wanted = list(dict.fromkeys(int(u) for u in user_ids))
    if wanted:
        found = {u.id: u for u in db.scalars(select(User).where(User.id.in_(wanted)))}
        missing = [u for u in wanted if u not in found]
        if missing:
            raise ValidationFailed("존재하지 않는 사용자입니다.",
                                   detail={"field": "user_ids", "ids": missing})
        inactive = [found[u].username for u in wanted if not found[u].is_active]
        if inactive:
            raise ValidationFailed("비활성 계정은 근무조에 넣을 수 없습니다.",
                                   detail={"users": inactive})
        clash = db.execute(
            select(User.display_name, RosterTeam.name)
            .select_from(RosterMember)
            .join(User, User.id == RosterMember.user_id)
            .join(RosterTeam, RosterTeam.id == RosterMember.team_id)
            .where(RosterMember.user_id.in_(wanted), RosterMember.team_id != team.id)).all()
        if clash:
            raise Conflict("이미 다른 조에 편성된 사람이 있습니다.",
                           detail={"conflicts": [{"name": n, "team": t} for n, t in clash]})
    if leader_id is not None and leader_id not in wanted:
        raise ValidationFailed("조장은 그 조의 구성원 중에서 고르십시오.",
                               detail={"field": "leader_id"})

    before = [m.user_id for m in team.members]
    keep = {m.user_id: m for m in list(team.members)}
    for uid, member in keep.items():
        if uid not in wanted:
            team.members.remove(member)
    for order, uid in enumerate(wanted):
        member = keep.get(uid)
        if member is None:
            member = RosterMember(team_id=team.id, user_id=uid)
            team.members.append(member)
        member.sort_order = order
        member.is_leader = (uid == leader_id)
    db.flush()
    db.refresh(team)

    record(db, action=actions.ROSTER_TEAM_CHANGE, ctx=ctx, user=actor,
           resource_type="ROSTER_TEAM", resource_id=team.id,
           before={"user_ids": before},
           after={"user_ids": wanted, "leader_id": leader_id})
    return team


def update_team(db: Session, team_id: int, changes: dict[str, Any], *, actor: User,
                ctx: RequestContext | None = None) -> RosterTeam:
    team = get_team_or_404(db, team_id)
    before = {"name": team.name, "phase_days": team.phase_days, "is_active": team.is_active}
    if changes.get("name"):
        team.name = str(changes["name"]).strip()[:40]
    if changes.get("phase_days") is not None:
        phase = int(changes["phase_days"])
        if not 0 <= phase < CYCLE_DAYS:
            raise ValidationFailed(f"주기 위치는 0 ~ {CYCLE_DAYS - 1} 사이여야 합니다.",
                                   detail={"field": "phase_days"})
        team.phase_days = phase
    if changes.get("is_active") is not None:
        team.is_active = bool(changes["is_active"])
    db.flush()
    record(db, action=actions.ROSTER_TEAM_CHANGE, ctx=ctx, user=actor,
           resource_type="ROSTER_TEAM", resource_id=team.id, before=before,
           after={"name": team.name, "phase_days": team.phase_days,
                  "is_active": team.is_active})
    return team


# --------------------------------------------------------------------------- 대근 · 맞교환 · 결원

def _assert_on_duty(db: Session, day: date, shift_code: str, user_id: int) -> None:
    row = staffing(db, day, shift_code)
    if user_id not in row["actual_user_ids"]:
        raise ValidationFailed("그 날 그 근무에 들어 있지 않은 사람입니다.",
                               detail={"work_date": day.isoformat(), "shift_code": shift_code})


def _assert_free(db: Session, day: date, shift_code: str, user_id: int) -> None:
    """같은 날 겹치는 근무에 이미 들어 있으면 막는다(이중 배정).

    주간(09~18)과 그 날 야간(18~익일 09)은 시간이 겹치지 않지만, 하루 두 번 세우는 것은
    4조 2교대에서 사고로 보아야 한다. 전날 야간을 선 사람이 다음 날 주간에 들어오는 것도
    같은 이유로 막는다(퇴근 직후 출근).
    """
    checks = [(day, SHIFT_DAY), (day, SHIFT_NIGHT)]
    if shift_code == SHIFT_DAY:
        checks.append((day - timedelta(days=1), SHIFT_NIGHT))
    for d, code in checks:
        if (d, code) == (day, shift_code):
            continue
        if user_id in staffing(db, d, code)["actual_user_ids"]:
            raise Conflict("같은 날(또는 바로 앞 야간) 근무에 이미 들어 있습니다.",
                           detail={"work_date": d.isoformat(), "shift_code": code})


def substitute(db: Session, *, work_date: date, shift_code: str, off_user_id: int,
               on_user_id: int | None, reason: str | None, actor: User,
               ctx: RequestContext | None = None) -> RosterOverride:
    """대근(on_user_id 있음) 또는 결원(on_user_id 없음)."""
    if shift_code not in SHIFT_TIMES:
        raise ValidationFailed("주간 · 야간 중 하나여야 합니다.", detail={"field": "shift_code"})
    _assert_on_duty(db, work_date, shift_code, off_user_id)
    if on_user_id is not None:
        if on_user_id == off_user_id:
            raise ValidationFailed("같은 사람으로는 대근할 수 없습니다.")
        user = db.get(User, on_user_id)
        if user is None or not user.is_active:
            raise ValidationFailed("대근자를 찾을 수 없거나 비활성 계정입니다.",
                                   detail={"field": "on_user_id"})
        _assert_free(db, work_date, shift_code, on_user_id)

    ovr = RosterOverride(work_date=work_date, shift_code=shift_code,
                         kind=OVR_SUB if on_user_id else OVR_OFF,
                         off_user_id=off_user_id, on_user_id=on_user_id,
                         reason=(reason or "").strip() or None, created_by=actor.id)
    db.add(ovr)
    db.flush()
    _notify(db, ovr, actor)
    record(db, action=actions.ROSTER_OVERRIDE, ctx=ctx, user=actor,
           resource_type="ROSTER", resource_id=ovr.id,
           after=_ovr_snapshot(ovr))
    return ovr


def swap(db: Session, *, first: dict[str, Any], second: dict[str, Any], reason: str | None,
         actor: User, ctx: RequestContext | None = None) -> list[RosterOverride]:
    """맞교환 — 두 근무를 서로 바꾼다. 두 줄로 적고 서로를 가리키게 한다.

    한쪽만 남는 상태가 생기지 않도록 **한 트랜잭션에서** 두 줄을 만든다.
    """
    a_date, a_shift, a_user = first["work_date"], first["shift_code"], first["user_id"]
    b_date, b_shift, b_user = second["work_date"], second["shift_code"], second["user_id"]
    if (a_date, a_shift, a_user) == (b_date, b_shift, b_user):
        raise ValidationFailed("같은 근무끼리는 맞교환할 수 없습니다.")
    _assert_on_duty(db, a_date, a_shift, a_user)
    _assert_on_duty(db, b_date, b_shift, b_user)

    clean = (reason or "").strip() or None
    one = RosterOverride(work_date=a_date, shift_code=a_shift, kind=OVR_SWAP,
                         off_user_id=a_user, on_user_id=b_user, reason=clean,
                         created_by=actor.id)
    two = RosterOverride(work_date=b_date, shift_code=b_shift, kind=OVR_SWAP,
                         off_user_id=b_user, on_user_id=a_user, reason=clean,
                         created_by=actor.id)
    db.add_all([one, two])
    db.flush()
    one.pair_id, two.pair_id = two.id, one.id
    db.flush()
    for ovr in (one, two):
        _notify(db, ovr, actor)
    record(db, action=actions.ROSTER_OVERRIDE, ctx=ctx, user=actor,
           resource_type="ROSTER", resource_id=one.id,
           after={"swap": [_ovr_snapshot(one), _ovr_snapshot(two)]})
    return [one, two]


def cancel(db: Session, override_id: int, *, reason: str | None, actor: User,
           ctx: RequestContext | None = None) -> list[RosterOverride]:
    """예외를 되돌린다. 행을 지우지 않고 취소로 적는다 — 무엇이 있었는지 남아야 한다."""
    ovr = db.get(RosterOverride, override_id)
    if ovr is None:
        raise NotFound("근무 변경 기록을 찾을 수 없습니다.")
    if ovr.canceled_at is not None:
        raise Conflict("이미 취소된 변경입니다.")

    affected = [ovr]
    if ovr.pair_id is not None:
        pair = db.get(RosterOverride, ovr.pair_id)
        if pair is not None and pair.canceled_at is None:
            affected.append(pair)       # 맞교환은 한쪽만 되돌릴 수 없다

    stamp = now()
    for row in affected:
        row.canceled_at = stamp
        row.canceled_by = actor.id
        row.cancel_reason = (reason or "").strip() or None
    db.flush()
    for row in affected:
        _notify(db, row, actor, canceled=True)
    record(db, action=actions.ROSTER_OVERRIDE_CANCEL, ctx=ctx, user=actor,
           resource_type="ROSTER", resource_id=ovr.id,
           before={"ids": [r.id for r in affected]},
           after={"canceled_at": stamp.isoformat(), "reason": reason})
    return affected


def history(db: Session, *, start: date, end: date, limit: int = 200) -> list[dict[str, Any]]:
    """근무 변경 이력 — 취소된 것도 보여 준다(무엇이 있었는지가 이력이다)."""
    rows = db.scalars(
        select(RosterOverride)
        .where(RosterOverride.work_date >= start, RosterOverride.work_date <= end)
        .order_by(RosterOverride.work_date, RosterOverride.id)
        .limit(limit)).all()
    return [_ovr_snapshot(r) for r in rows]


def _ovr_snapshot(ovr: RosterOverride) -> dict[str, Any]:
    """감사 기록과 응답이 같은 모양을 쓴다. 날짜·시각은 ISO 문자열로 — 감사 payload 는 JSON 이다."""
    return {
        "id": ovr.id, "work_date": ovr.work_date.isoformat(), "shift_code": ovr.shift_code,
        "shift_label": SHIFT_LABEL.get(ovr.shift_code, ovr.shift_code),
        "kind": ovr.kind,
        "off_user_id": ovr.off_user_id,
        "off_user_name": ovr.off_user.display_name if ovr.off_user else None,
        "on_user_id": ovr.on_user_id,
        "on_user_name": ovr.on_user.display_name if ovr.on_user else None,
        "reason": ovr.reason, "created_by": ovr.created_by,
        "created_at": ovr.created_at.isoformat() if ovr.created_at else None,
        "canceled_at": ovr.canceled_at.isoformat() if ovr.canceled_at else None,
        "cancel_reason": ovr.cancel_reason,
        "pair_id": ovr.pair_id,
    }


def _notify(db: Session, ovr: RosterOverride, actor: User, *, canceled: bool = False) -> None:
    """근무가 바뀐 당사자 둘에게 알린다 — 달력을 다시 보러 오지 않아도 알게."""
    from app.services import notification_service as ns

    label = SHIFT_LABEL.get(ovr.shift_code, ovr.shift_code)
    when = f"{ovr.work_date:%m/%d} {label}"
    verb = "취소되었습니다" if canceled else "바뀌었습니다"
    for uid in {ovr.off_user_id, ovr.on_user_id} - {None, actor.id}:
        ns.notify(db, user_id=uid, type_=ns.T_SHIFT_CHANGE,
                  title=f"근무 변경: {when}",
                  body=f"{actor.display_name} 님이 등록한 근무 변경이 {verb}.",
                  link_type="ROSTER", link_id=ovr.id,
                  dedup_key=f"roster:{ovr.id}:{'cancel' if canceled else 'set'}")


# --------------------------------------------------------------------------- 설치 기본값

#: 4조 2교대 기본 편성. 조를 4일씩 밀어 두면 매일 주간 1조 · 야간 1조가 된다.
DEFAULT_TEAMS = [("A", "1조", 0, 1), ("B", "2조", 4, 2), ("C", "3조", 8, 3), ("D", "4조", 12, 4)]


def ensure_teams(db: Session) -> int:
    created = 0
    for code, name, phase, order in DEFAULT_TEAMS:
        if db.scalar(select(RosterTeam).where(RosterTeam.code == code)) is None:
            db.add(RosterTeam(code=code, name=name, phase_days=phase, sort_order=order))
            created += 1
    if created:
        db.flush()
    return created


def coverage_check(db: Session, start: date, days: int = 32) -> dict[str, Any]:
    """주기가 실제로 맞물리는지 — 매일 주간 1조 · 야간 1조인지 세어 본다.

    조의 주기 위치(phase_days)를 고치면 하루에 두 조가 겹치거나 빈 날이 생길 수 있다.
    설정 화면이 저장 전에 이 함수로 확인한다.
    """
    problems: list[dict[str, Any]] = []
    at = plan(db)
    for offset in range(days):
        day = start + timedelta(days=offset)
        counts = {SHIFT_DAY: [], SHIFT_NIGHT: [], SHIFT_OFF: []}
        for team in at.teams:
            counts[shift_of(db, team, day, at=at)].append(team.code)
        if len(counts[SHIFT_DAY]) != 1 or len(counts[SHIFT_NIGHT]) != 1:
            problems.append({"day": day, "day_teams": counts[SHIFT_DAY],
                             "night_teams": counts[SHIFT_NIGHT]})
    return {"start": start, "days": days, "ok": not problems, "problems": problems}
