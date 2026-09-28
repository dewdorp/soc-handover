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
    #: 비밀번호 보관(장비 계정)의 암호화 키 — base64 32바이트. 설치 프로그램이 .env 에 만들어 넣는다.
    #: SECRET_KEY 와 따로 두는 이유: SECRET_KEY 는 유출 시 바꾸는 값인데, 거기서 파생하면
    #: 바꾸는 순간 보관된 비밀번호가 전부 잠긴다.
    VAULT_KEY: str = ""
    #: 키 교체용 새 키. 넣고 manage.py vault-rekey 를 돌리면 전부 새 키로 다시 암호화한다.
    VAULT_KEY_NEXT: str = ""

    # --- DB ---
    DATABASE_URL: str = ""
    DB_ECHO: bool = False
    SQL_POOL_SIZE: int = 10

    # --- 경로 ---
    DATA_DIR: Path = PROJECT_ROOT / "data"
    BACKUP_DIR: Path = PROJECT_ROOT / "backup"
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    #: 로그를 콘솔(stderr)에도 쓸지. 서비스 모드는 stderr 를 파일로 받으므로 끈다 —
    #: 켜 두면 회전되지 않는 uvicorn.err.log 가 끝없이 커진다(파일 로그는 app.log 가 10MB×10 으로 회전).
    LOG_CONSOLE: bool = True
    FRONTEND_DIST: Path = PROJECT_ROOT / "frontend" / "dist"

    # --- 기능 한도 ---
    MAX_PAGE_SIZE: int = 200
    DEFAULT_PAGE_SIZE: int = 50
    EXPORT_MAX_ROWS: int = 100_000
    UPLOAD_MAX_MB: int = 20
    #: Excel Import 는 연도별 수천 행 × 여러 Sheet 라 첨부보다 크게 잡는다.
    IMPORT_MAX_MB: int = 200
    #: Export 다운로드 링크 유효 시간(분). 지나면 파일을 지운다.
    EXPORT_TTL_MINUTES: int = 60
    #: 첨부 백신 연동(FR-I-04 확장점). 비우면 검사하지 않는다. {path} 자리에 파일 경로가 들어간다.
    #: 예) "C:\Program Files\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File {path} -DisableRemediation
    #: 종료코드 0 = 깨끗, 그 밖 = 위험으로 보고 거절한다. 실행 자체가 실패해도 거절한다(안전한 쪽).
    ATTACHMENT_SCAN_COMMAND: str = ""
    ATTACHMENT_SCAN_TIMEOUT_SEC: int = 120
    #: 할일 마감 알림(임박·지연)을 몇 분마다 돌릴지. 0 이면 끈다(테스트는 0).
    REMINDER_INTERVAL_MIN: int = 30

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
