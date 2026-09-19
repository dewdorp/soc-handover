"""v1 라우터 집합. main.py 는 이 하나만 등록한다."""
from fastapi import APIRouter

from app.api.v1 import (admin, auth, exports, handovers, imports, notifications, reference,
                        saved_views, schedules, search, shift, system, tasks, users)

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
api_router.include_router(shift.router)
api_router.include_router(notifications.router)
api_router.include_router(tasks.router)
api_router.include_router(schedules.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
