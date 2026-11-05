"""1.2.0 → 1.3.0 올리기 — 쌓여 있던 자료가 그대로 보이는가.

이 판에서 가장 되돌리기 어려운 것은 **열람 그룹 이관**이다. 잘못 만들면 두 가지로 터진다.

  · 너무 넓게: 기존 자료를 '전체 공개'로 바꿔 버린다 → 그룹을 나누는 의미가 사라진다.
  · 너무 좁게: 아무 그룹에도 넣지 않는다 → 올린 다음 날 아침에 전 직원이 빈 목록을 본다.

그래서 1.2.0 모양의 DB 를 실제로 만들어 자료를 넣고, 마이그레이션을 끝까지 올린 뒤
확인한다. 서버 코드가 아니라 **SQL 로** 넣는다 — 지금 모델로 넣으면 1.2.0 상태를
재현하는 것이 아니다.

느리므로(프로세스 두 번) 따로 두었다. `pytest tests/api/test_upgrade_1_2_to_1_3.py`
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]

#: 1.2.0 의 마지막 리비전(가져오기 중단). 여기까지가 '올리기 전' 상태다.
REV_1_2_0 = "b4d7f1c6a903"


def _alembic(url: str, target: str) -> None:
    env = {**os.environ, "DATABASE_URL": url, "PYTHONUTF8": "1",
           "SECRET_KEY": "upgrade-test-secret-0123456789-0123456789",
           "APP_ENV": "dev"}
    done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", target],
                          cwd=BACKEND, env=env, capture_output=True, text=True,
                          encoding="utf-8")
    assert done.returncode == 0, f"alembic upgrade {target} 실패:\n{done.stderr[-3000:]}"


@pytest.fixture
def upgraded(tmp_path):
    """1.2.0 모양 DB + 자료 → 끝까지 올린 뒤의 엔진."""
    url = f"sqlite+pysqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    _alembic(url, REV_1_2_0)

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO roles (code, name, sort_order, created_at, updated_at) "
            "VALUES ('ADMIN','관리자',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
            "       ('ANALYST','근무자',3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text(
            "INSERT INTO companies (name, sort_order, is_active, created_at, updated_at) "
            "VALUES ('가람은행', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        conn.execute(text(
            "INSERT INTO handover_statuses (code, name, category, sort_order, is_active, is_system,"
            "                               created_at, updated_at) "
            "VALUES ('NEW','신규','OPEN',10,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text(
            "INSERT INTO priorities (code, name, level, is_active, created_at, updated_at) "
            "VALUES ('NORMAL','보통',2,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        for name, role in (("old_admin", "ADMIN"), ("old_day", "ANALYST"), ("old_night", "ANALYST")):
            conn.execute(text(
                "INSERT INTO users (username, display_name, auth_provider, role_code, is_active,"
                "                   must_change_password, failed_login_count, created_at, updated_at) "
                "VALUES (:u, :u, 'local', :r, 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"u": name, "r": role})
        for i in range(5):
            conn.execute(text(
                "INSERT INTO handovers (company_id, title, content, status_code, priority_code,"
                "                       registered_date, current_version_no, ack_state_cache,"
                "                       carry_count, is_important, is_pinned, is_recurring,"
                "                       is_deleted, created_at, updated_at) "
                "VALUES (1, :t, '쌓여 있던 내용', 'NEW', 'NORMAL', '2026-01-10', 1, 'NONE',"
                "        0, 0, 0, 0, :deleted, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"t": f"1.2.0 때 쓴 업무 {i}", "deleted": 1 if i == 4 else 0})
        # 담당자가 있는 건 — 올린 뒤 '대표 담당'으로 들어가야 한다
        conn.execute(text(
            "UPDATE handovers SET assignee_id = (SELECT id FROM users WHERE username='old_day') "
            "WHERE id IN (1, 2)"))
    engine.dispose()

    _alembic(url, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


class TestExistingDataKeepsBeingVisible:
    def test_unclassified_group_is_created_once(self, upgraded):
        with upgraded.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, code, name, is_active FROM groups WHERE code = 'UNCLASSIFIED'")).all()
        assert len(rows) == 1
        assert rows[0].name == "미분류"
        assert rows[0].is_active

    def test_every_existing_user_is_a_member(self, upgraded):
        with upgraded.connect() as conn:
            users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
            members = conn.execute(text(
                "SELECT COUNT(*) FROM user_groups ug JOIN groups g ON g.id = ug.group_id "
                "WHERE g.code = 'UNCLASSIFIED'")).scalar_one()
            defaults = conn.execute(text(
                "SELECT COUNT(*) FROM user_groups WHERE is_default = 1")).scalar_one()
        assert members == users == 3, "한 사람이라도 빠지면 그 사람은 빈 목록을 본다"
        assert defaults == users, "기본 그룹이 없으면 새 글을 어디에 올릴지 정해지지 않는다"

    def test_every_existing_handover_lands_in_the_group(self, upgraded):
        with upgraded.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM handovers")).scalar_one()
            linked = conn.execute(text(
                "SELECT COUNT(*) FROM handover_groups hg JOIN groups g ON g.id = hg.group_id "
                "WHERE g.code = 'UNCLASSIFIED'")).scalar_one()
        assert linked == total == 5, "지운 건까지 넣어야 복구했을 때 보인다"

    def test_nothing_becomes_public(self, upgraded):
        with upgraded.connect() as conn:
            public = conn.execute(text(
                "SELECT COUNT(*) FROM handovers WHERE visibility = 'ALL'")).scalar_one()
            grouped = conn.execute(text(
                "SELECT COUNT(*) FROM handovers WHERE visibility = 'GROUPS'")).scalar_one()
        assert public == 0, "쌓인 자료를 전체 공개로 바꾸면 안 된다(§3)"
        assert grouped == 5

    def test_the_same_people_still_see_the_same_rows(self, upgraded):
        """올리기 전에 보이던 5건이 올린 뒤에도 그대로 보인다 — 실제 판정 함수로 확인한다."""
        from sqlalchemy.orm import Session

        from app.models.handover import Handover
        from app.models.user import User
        from app.services import group_service

        with Session(upgraded) as db:
            for username in ("old_admin", "old_day", "old_night"):
                user = db.query(User).filter_by(username=username).one()
                visible = db.query(Handover).filter(
                    Handover.is_deleted.is_(False),
                    group_service.visible_clause(db, user.id)).count()
                assert visible == 4, f"{username} 에게 보이던 건수가 달라졌다"


class TestAssigneesBecomeOwners:
    def test_existing_assignee_becomes_the_representative_owner(self, upgraded):
        """담당자가 있던 건은 그 사람이 '대표 담당'으로 들어간다 — 보이는 것이 달라지지 않게."""
        with upgraded.connect() as conn:
            rows = conn.execute(text(
                "SELECT h.id, p.user_id, p.role FROM handovers h "
                "JOIN handover_participants p ON p.handover_id = h.id")).all()
            with_assignee = conn.execute(text(
                "SELECT COUNT(*) FROM handovers WHERE assignee_id IS NOT NULL")).scalar_one()
        assert len(rows) == with_assignee
        assert all(r.role == "OWNER" for r in rows)

    def test_request_flow_starts_empty(self, upgraded):
        with upgraded.connect() as conn:
            states = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT request_state FROM handovers")).all()}
        assert states == {"NONE"}, "올리자마자 의뢰 중인 건이 생기면 안 된다"


class TestRosterAndRemindersArrive:
    def test_four_teams_exist_with_no_people(self, upgraded):
        with upgraded.connect() as conn:
            teams = conn.execute(text(
                "SELECT code, phase_days FROM roster_teams ORDER BY sort_order")).all()
            members = conn.execute(text("SELECT COUNT(*) FROM roster_members")).scalar_one()
        assert [t.code for t in teams] == ["A", "B", "C", "D"]
        assert [t.phase_days for t in teams] == [0, 4, 8, 12]
        assert members == 0, "실제 명단은 현장에서 넣는다"

    def test_reminder_table_is_empty_not_missing(self, upgraded):
        with upgraded.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM schedule_reminders")).scalar_one() == 0


class TestDowngradeLeavesNoDebris:
    def test_rolling_back_drops_the_new_tables(self, tmp_path):
        """되돌릴 수 있어야 한다 — 올리다 문제가 생겼을 때 돌아갈 자리가 있어야 한다."""
        url = f"sqlite+pysqlite:///{(tmp_path / 'down.db').as_posix()}"
        _alembic(url, "head")
        env = {**os.environ, "DATABASE_URL": url, "PYTHONUTF8": "1",
               "SECRET_KEY": "upgrade-test-secret-0123456789-0123456789", "APP_ENV": "dev"}
        done = subprocess.run([sys.executable, "-m", "alembic", "downgrade", REV_1_2_0],
                              cwd=BACKEND, env=env, capture_output=True, text=True,
                              encoding="utf-8")
        assert done.returncode == 0, done.stderr[-3000:]

        engine = create_engine(url)
        with engine.connect() as conn:
            names = {r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'")).all()}
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(handovers)")).all()}
        engine.dispose()
        assert not ({"groups", "user_groups", "handover_groups",
                     "roster_teams", "roster_members", "roster_overrides",
                     "schedule_reminders", "handover_participants"} & names)
        assert "visibility" not in cols
        assert "request_state" not in cols
