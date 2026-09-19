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
    created = {"roles": 0, "statuses": 0, "priorities": 0, "shifts": 0, "settings": 0}

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
    return user


def ensure_default_company(db: Session, name: str = "미지정") -> Company:
    from sqlalchemy import select
    company = db.scalar(select(Company).where(Company.name == name))
    if company is None:
        company = Company(name=name, code="UNSPEC", sort_order=999)
        db.add(company)
        db.flush()
    return company
