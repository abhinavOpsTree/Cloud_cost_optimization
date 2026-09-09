from fastapi import APIRouter

from app.core.config import settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "application": settings.app_name,
        "source": "SpendSmart / UnitEconPro",
        "processing_scope": "EC2 only",
    }
