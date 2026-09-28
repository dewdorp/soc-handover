"""운영/개발용 CLI.

사용 예)
  python manage.py bootstrap                     기준 데이터 구성
  python manage.py create-admin --username admin 관리자 생성(비밀번호는 입력 프롬프트)
  python manage.py check                         DB 연결 및 마이그레이션 상태 확인
  python manage.py archive-audit [--dry-run]     보존기간 지난 감사로그 보관 후 정리
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


def cmd_archive_audit(args) -> int:
    """보존기간이 지난 감사로그를 backup/audit-archive 로 옮긴 뒤 지운다(backup.ps1 이 매일 실행)."""
    from app.services import audit_archive_service
    with SessionLocal() as db:
        try:
            r = audit_archive_service.archive_expired(db, days=args.days, dry_run=args.dry_run)
        except Exception as exc:
            print(f"감사로그 보관 정리 실패: {exc}", file=sys.stderr)
            return 1
    if args.dry_run:
        print(f"보존 {r['days']}일 기준, 대상 {r['count']}건 (확인만, 지우지 않음)")
    elif r["count"]:
        print(f"감사로그 {r['count']}건 보관 후 정리 → {r['file']}")
    else:
        print(f"보존 {r['days']}일이 지난 감사로그 없음")
    return 0



def cmd_vault_key(_args) -> int:
    """비밀번호 보관용 키를 만들어 준다(.env 에 넣는 것은 사람이 한다).

    이미 키가 있으면 만들지 않는다 — 덮어쓰면 보관된 비밀번호를 전부 못 읽게 된다.
    """
    from app.core import crypto
    from app.core.config import settings
    if settings.VAULT_KEY.strip():
        print("VAULT_KEY 가 이미 .env 에 있습니다. 바꾸려면 vault-rekey 를 쓰십시오"
              "(그냥 바꾸면 보관된 비밀번호를 못 읽습니다).")
        return 1
    print("아래 한 줄을 .env 에 넣고 앱을 다시 시작하십시오. 이 값을 잃으면 되살릴 수 없습니다.")
    print(f"VAULT_KEY={crypto.generate_key()}")
    return 0


def cmd_vault_rekey(_args) -> int:
    """보관된 비밀번호를 새 키(.env 의 VAULT_KEY_NEXT)로 다시 암호화한다."""
    from app.core import crypto
    from app.core.config import settings
    from app.services import credential_service
    if not settings.VAULT_KEY_NEXT.strip():
        print("먼저 .env 에 새 키를 넣으십시오:", file=sys.stderr)
        print(f"VAULT_KEY_NEXT={crypto.generate_key()}", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        try:
            r = credential_service.rekey(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"다시 암호화 실패(아무것도 바꾸지 않았습니다): {exc}", file=sys.stderr)
            return 1
    print(f"{r['reencrypted']}건을 새 키로 다시 암호화했습니다.")
    print("이제 .env 에서 VAULT_KEY 를 새 값으로 바꾸고(VAULT_KEY_NEXT 의 값), "
          "VAULT_KEY_NEXT 줄은 지운 뒤 앱을 다시 시작하십시오.")
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

    sub.add_parser("vault-key", help="비밀번호 보관용 키(VAULT_KEY) 만들기")
    sub.add_parser("vault-rekey", help="보관된 비밀번호를 VAULT_KEY_NEXT 로 다시 암호화")

    p_arch = sub.add_parser("archive-audit", help="보존기간 지난 감사로그를 보관 파일로 옮긴 뒤 정리")
    p_arch.add_argument("--days", type=int, default=None, help="보존 일수(기본: 설정 retention.audit_days, 최소 365)")
    p_arch.add_argument("--dry-run", action="store_true", help="대상 건수만 확인")

    args = parser.parse_args()
    handlers = {
        "bootstrap": cmd_bootstrap,
        "create-admin": cmd_create_admin,
        "check": cmd_check,
        "archive-audit": cmd_archive_audit,
        "vault-key": cmd_vault_key,
        "vault-rekey": cmd_vault_rekey,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
