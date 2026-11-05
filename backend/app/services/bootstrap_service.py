"""초기 기준 데이터 구성. 설치 시 1회, 이후 기동 시 누락분만 보충한다."""
from __future__ import annotations

from datetime import time

from sqlalchemy.orm import Session

from app.core.security import hash_password, validate_password_policy
from app.models.reference import Company, HandoverStatus, Priority, Shift
from app.models.user import Role, User
from app.services import settings_service

ROLES = [
    ("ADMIN", "관리자", "전체 관리 권한", 1),
    ("MANAGER", "근무 관리자", "전체 조회 및 업무/중요업무 관리", 2),
    ("ANALYST", "SOC 근무자", "일반 근무자", 3),
]

# (code, name, category, color, icon, sort)
STATUSES = [
    ("NEW", "신규", "OPEN", "#2563eb", "circle", 10),
    ("IN_PROGRESS", "진행중", "OPEN", "#0891b2", "half-circle", 20),
    ("NEED_CHECK", "확인필요", "OPEN", "#d97706", "alert", 30),
    ("ACTION_PLANNED", "조치예정", "OPEN", "#7c3aed", "calendar", 40),
    ("WAITING", "대기", "WAITING", "#64748b", "pause", 50),
    ("HOLD", "보류", "WAITING", "#78716c", "pause-circle", 60),
    ("DONE", "완료", "CLOSED", "#16a34a", "check", 70),
    ("CANCELED", "취소", "CLOSED", "#94a3b8", "x", 80),
]

# (code, name, level, color, icon)
PRIORITIES = [
    ("URGENT", "긴급", 0, "#dc2626", "alert-octagon"),
    ("HIGH", "높음", 1, "#ea580c", "triangle-up"),
    ("NORMAL", "보통", 2, "#475569", "minus"),
    ("LOW", "낮음", 3, "#94a3b8", "triangle-down"),
]

# (code, name, start, end, crosses_midnight, sort) — ASSUMPTIONS B-01
# 운영 확인: 주간·야간 2교대. 관리자가 PATCH /shifts 로 바꿀 수 있다.
SHIFTS = [
    ("DAY", "주간", time(9, 0), time(18, 0), False, 10),
    ("NIGHT", "야간", time(18, 0), time(9, 0), True, 20),
]


def ensure_reference_data(db: Session) -> dict[str, int]:
    from app.services import group_service

    created = {"roles": 0, "statuses": 0, "priorities": 0, "shifts": 0, "settings": 0,
               "groups": 0}

    # 열람 그룹의 기본 자리('미분류'). 없으면 만든다 — 글에는 반드시 그룹이 하나는 있어야 한다.
    from sqlalchemy import func, select

    from app.models.group import Group
    before = db.scalar(select(func.count()).select_from(Group)) or 0
    group_service.ensure_unclassified(db)
    created["groups"] = (db.scalar(select(func.count()).select_from(Group)) or 0) - before

    for code, name, desc, order in ROLES:
        if db.get(Role, code) is None:
            db.add(Role(code=code, name=name, description=desc, sort_order=order))
            created["roles"] += 1

    for code, name, category, color, icon, order in STATUSES:
        if db.get(HandoverStatus, code) is None:
            db.add(HandoverStatus(code=code, name=name, category=category, color=color,
                                  icon=icon, sort_order=order, is_active=True, is_system=True))
            created["statuses"] += 1

    for code, name, level, color, icon in PRIORITIES:
        if db.get(Priority, code) is None:
            db.add(Priority(code=code, name=name, level=level, color=color, icon=icon))
            created["priorities"] += 1

    db.flush()

    from sqlalchemy import select
    for code, name, start, end, crosses, order in SHIFTS:
        if db.scalar(select(Shift).where(Shift.code == code)) is None:
            db.add(Shift(code=code, name=name, start_time=start, end_time=end,
                         crosses_midnight=crosses, sort_order=order))
            created["shifts"] += 1

    from app.services import roster_service
    created["roster_teams"] = roster_service.ensure_teams(db)

    created["settings"] = settings_service.ensure_defaults(db)
    db.flush()
    return created


def create_admin(db: Session, *, username: str, display_name: str, password: str,
                 must_change: bool = True) -> User:
    """관리자 계정 생성. 비밀번호는 호출자가 대화식으로 받아 넘긴다(소스에 두지 않는다)."""
    from sqlalchemy import select

    problems = validate_password_policy(password, username)
    if problems:
        raise ValueError("비밀번호 정책 위반: " + " / ".join(problems))

    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, display_name=display_name, role_code="ADMIN")
        db.add(user)
    user.password_hash = hash_password(password)
    user.role_code = "ADMIN"
    user.is_active = True
    user.must_change_password = must_change
    user.failed_login_count = 0
    user.locked_until = None
    db.flush()

    # 설치 직후의 관리자는 어느 그룹에도 속하지 않는다 — 그러면 자기가 쓴 글만 보인다.
    # '미분류'를 기본 그룹으로 넣어 준다(관리자는 그 뒤에 실제 그룹을 만들어 옮긴다).
    from app.models.group import UserGroup
    from app.services import group_service

    group = group_service.ensure_unclassified(db)
    if not group_service.my_group_ids(db, user.id):
        db.add(UserGroup(user_id=user.id, group_id=group.id, is_default=True))
        db.flush()
    return user


#: '매칭 실패' 행이 모이는 자리. 코드가 신원이고 이름은 현장에서 바꿔 쓸 수 있다.
UNSPEC_CODE = "UNSPEC"


def ensure_default_company(db: Session, name: str = "미지정") -> Company:
    """예약 코드(UNSPEC) 자리를 보장한다 — **코드로 찾는다**.

    현장에서 표시명을 '공통' 등으로 바꿔 쓰는 일이 있다. 이름으로 찾으면 못 찾고 다시 만들다가
    code 고유키에서 터져 가져오기 전체가 멈춘다(재현 ⑤). 찾으면 이름은 건드리지 않는다.
    이름만 같고 코드가 다른 회사가 이미 있으면 그 회사를 예약 자리로 삼는다(중복 회사 방지).
    """
    from sqlalchemy import or_, select
    company = db.scalar(select(Company).where(Company.code == UNSPEC_CODE))
    if company is not None:
        return company
    by_name = db.scalar(select(Company).where(Company.name == name))
    if by_name is not None:
        if by_name.code is None:
            by_name.code = UNSPEC_CODE     # 코드 없이 만들어진 과거 데이터를 예약 자리로 승격
            db.flush()
        return by_name
    company = Company(name=name, code=UNSPEC_CODE, sort_order=999)
    db.add(company)
    db.flush()
    return company
