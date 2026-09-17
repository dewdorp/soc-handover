"""애플리케이션 설정. 모든 비밀값은 .env 에서만 읽는다(하드코딩 금지)."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 기본 ---
    APP_NAME: str = "SOC Handover Platform"
    APP_ENV: Literal["dev", "prod", "test"] = "dev"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8080
    TIMEZONE: str = "Asia/Seoul"
    ENABLE_DOCS: bool = True

    # --- 보안 ---
    SECRET_KEY: str = ""
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_HOURS: int = 12
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None
    SSL_CERTFILE: str | None = None
    SSL_KEYFILE: str | None = None
    LOGIN_MAX_FAILS: int = 5
    LOGIN_LOCK_MINUTES: int = 5

    # --- DB ---
    DATABASE_URL: str = ""
    DB_ECHO: bool = False
    SQL_POOL_SIZE: int = 10

    # --- 경로 ---
    DATA_DIR: Path = PROJECT_ROOT / "data"
    BACKUP_DIR: Path = PROJECT_ROOT / "backup"
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    FRONTEND_DIST: Path = PROJECT_ROOT / "frontend" / "dist"

    # --- 기능 한도 ---
    MAX_PAGE_SIZE: int = 200
    DEFAULT_PAGE_SIZE: int = 50
    EXPORT_MAX_ROWS: int = 100_000
    UPLOAD_MAX_MB: int = 20

    # --- LLM (선택) ---
    LLM_PROVIDER: Literal["disabled", "ollama", "openai_compatible"] = "disabled"
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL: str | None = None
    LLM_EMBED_MODEL: str | None = None
    LLM_TIMEOUT_SEC: int = 60

    # --- 개발 편의 ---
    DEV_CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def _default_db(cls, v: str) -> str:
        if v:
            return v
        # PostgreSQL 미설정 시 개발용 SQLite fallback (ASSUMPTIONS A-01)
        return f"sqlite+pysqlite:///{(PROJECT_ROOT / 'data' / 'soc_handover.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "prod"

    @property
    def attachments_dir(self) -> Path:
        return self.DATA_DIR / "attachments"

    @property
    def imports_dir(self) -> Path:
        return self.DATA_DIR / "imports"

    @property
    def exports_dir(self) -> Path:
        return self.DATA_DIR / "exports"

    def ensure_dirs(self) -> None:
        for p in (self.DATA_DIR, self.BACKUP_DIR, self.LOG_DIR,
                  self.attachments_dir, self.imports_dir, self.exports_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.SECRET_KEY:
        if s.is_production:
            raise RuntimeError(
                "SECRET_KEY가 설정되지 않았습니다. .env 에 SECRET_KEY를 지정하십시오. "
                "(install.ps1 이 자동 생성합니다)"
            )
        # dev/test: 프로세스 수명 동안만 유효한 임시 키
        s.SECRET_KEY = secrets.token_urlsafe(48)
    s.ensure_dirs()
    return s


settings = get_settings()
