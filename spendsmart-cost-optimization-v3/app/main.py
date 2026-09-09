from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.core.config import settings
from app.core.logger import configure_logging
from app.db.session import Base, engine

import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="3.0.0",
    description=(
        "UnitEconPro / SpendSmart source catalog with EC2-only processing."
    ),
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "source": "SpendSmart / UnitEconPro",
        "processing_scope": "EC2 only",
        "docs": "/docs",
        "catalog": "/api/source-catalog/endpoints",
    }
