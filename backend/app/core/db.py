"""DB 엔진/세션. PostgreSQL(운영) · SQLite(개발/테스트) 양쪽을 지원한다."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _make_engine() -> Engine:
    if settings.is_sqlite:
        eng = create_engine(
            settings.DATABASE_URL,
            echo=settings.DB_ECHO,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragma(dbapi_conn, _rec):  # pragma: no cover - 환경 설정
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return eng

    return create_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        future=True,
        pool_size=settings.SQL_POOL_SIZE,
        max_overflow=5,
        pool_pre_ping=True,
    )


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성. 요청 1건 = 세션 1개."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dialect_name() -> str:
    return engine.dialect.name
