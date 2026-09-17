"""운영/개발용 CLI.

사용 예)
  python manage.py bootstrap                     기준 데이터 구성
  python manage.py create-admin --username admin 관리자 생성(비밀번호는 입력 프롬프트)
  python manage.py check                         DB 연결 및 마이그레이션 상태 확인
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.services import bootstrap_service


def _read_password(env_key: str = "SOC_ADMIN_PASSWORD") -> str:
    """비밀번호는 인자로 받지 않는다(프로세스 목록/히스토리 노출 방지)."""
    value = os.environ.get(env_key)
    if value:
        return value
    if not sys.stdin.isatty():
        raise SystemExit(
            f"비밀번호를 입력할 수 없습니다. 환경변수 {env_key} 를 설정하거나 "
            "대화형 터미널에서 실행하십시오."
        )
    first = getpass.getpass("관리자 비밀번호(12자 이상, 3종 조합): ")
    second = getpass.getpass("다시 입력: ")
    if first != second:
        raise SystemExit("비밀번호가 일치하지 않습니다.")
    return first


def cmd_bootstrap(_args) -> int:
    with SessionLocal() as db:
        created = bootstrap_service.ensure_reference_data(db)
        bootstrap_service.ensure_default_company(db)
        db.commit()
    print("기준 데이터 구성 완료:", created)
    return 0


def cmd_create_admin(args) -> int:
    password = _read_password()
    with SessionLocal() as db:
        bootstrap_service.ensure_reference_data(db)
        try:
            user = bootstrap_service.create_admin(
                db, username=args.username, display_name=args.display_name,
                password=password, must_change=not args.no_force_change,
            )
        except ValueError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 2
        db.commit()
        print(f"관리자 계정 준비 완료: {user.username}"
              + (" (최초 로그인 시 비밀번호 변경 필요)" if user.must_change_password else ""))
    return 0


def cmd_check(_args) -> int:
    print(f"DATABASE : {'sqlite(개발용)' if settings.is_sqlite else 'postgresql'}")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"연결     : OK")
        print(f"마이그레이션 : {rev}")
    except Exception as exc:
        print(f"연결 실패: {exc}", file=sys.stderr)
        return 1
    if settings.is_sqlite:
        print("경고     : 운영에는 PostgreSQL을 사용하십시오(ASSUMPTIONS A-01).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="SOC Handover 관리 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="기준 데이터(역할/상태/중요도/교대/설정) 구성")

    p_admin = sub.add_parser("create-admin", help="관리자 계정 생성/갱신")
    p_admin.add_argument("--username", default="admin")
    p_admin.add_argument("--display-name", default="시스템 관리자")
    p_admin.add_argument("--no-force-change", action="store_true",
                         help="최초 로그인 시 비밀번호 변경 강제를 해제")

    sub.add_parser("check", help="DB 연결/마이그레이션 상태 확인")

    args = parser.parse_args()
    handlers = {
        "bootstrap": cmd_bootstrap,
        "create-admin": cmd_create_admin,
        "check": cmd_check,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
