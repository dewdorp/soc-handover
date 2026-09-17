"""v1 라우터 집합. main.py 는 이 하나만 등록한다."""
from fastapi import APIRouter

from app.api.v1 import auth, reference, system, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(reference.router)

__all__ = ["api_router"]
