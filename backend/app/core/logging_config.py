"""로깅 설정. 오류 상세는 파일에만 남기고 사용자에게는 request_id만 노출한다."""
from __future__ import annotations

import logging
import logging.handlers

from app.core.config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-18s %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if settings.LOG_CONSOLE:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.LOG_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    error_handler = logging.handlers.RotatingFileHandler(
        settings.LOG_DIR / "error.log", maxBytes=10 * 1024 * 1024, backupCount=10,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    root.addHandler(error_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True
