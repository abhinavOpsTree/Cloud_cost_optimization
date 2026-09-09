from fastapi import APIRouter

from app.api.routes import ai, catalog, ec2, health, ingestion, source


router = APIRouter(prefix="/api")

router.include_router(health.router)
router.include_router(catalog.router)
router.include_router(source.router)
router.include_router(ingestion.router)
router.include_router(ec2.router)
router.include_router(ai.router)
