"""FastAPI 앱 조립. 비즈니스 로직은 여기에 두지 않는다(§88)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging_config import setup_logging
from app.core.middleware import register_middleware

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("%s 기동 · env=%s · db=%s", settings.APP_NAME, settings.APP_ENV,
             "sqlite(개발용)" if settings.is_sqlite else "postgresql")
    if settings.is_sqlite and settings.is_production:
        log.warning("운영 환경에서 SQLite를 사용하고 있습니다. PostgreSQL 사용을 권장합니다.")
    yield
    log.info("%s 종료", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/api/docs" if settings.ENABLE_DOCS else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.ENABLE_DOCS else None,
        lifespan=lifespan,
    )
    register_middleware(app)
    register_error_handlers(app)
    app.include_router(api_router)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """운영 모드에서는 빌드된 SPA를 같은 포트에서 서빙한다(리버스 프록시 불필요)."""
    dist = settings.FRONTEND_DIST
    index = dist / "index.html"
    if not index.exists():
        @app.get("/", include_in_schema=False)
        def _no_frontend():
            return JSONResponse({
                "message": "프론트엔드가 아직 빌드되지 않았습니다. frontend 에서 npm run build 를 실행하십시오.",
                "api": "/api/v1/health",
            })
        return

    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "not_found", "message": "대상을 찾을 수 없습니다.",
                                 "detail": {}}, status_code=404)
        candidate = (dist / full_path).resolve()
        # dist 밖으로 나가는 경로 요청은 거부한다(Path Traversal 방어)
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
