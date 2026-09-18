"""v1 라우터 집합. main.py 는 이 하나만 등록한다."""
from fastapi import APIRouter

from app.api.v1 import (auth, exports, handovers, imports, reference, saved_views, search,
                        system, users)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(reference.router)
# search 는 handovers 보다 먼저 등록한다. /handovers/search·facets 가
# /handovers/{handover_id} 에 먹히지 않도록 구체적인 경로를 앞에 둔다.
api_router.include_router(search.router)
api_router.include_router(handovers.router)
api_router.include_router(saved_views.router)
api_router.include_router(imports.router)
api_router.include_router(exports.router)

__all__ = ["api_router"]
