from fastapi import APIRouter

from app.services.spendsmart.endpoint_registry import ENDPOINTS
from app.services.spendsmart.schema_registry import SWAGGER_SCHEMA_NAMES


router = APIRouter(
    prefix="/source-catalog",
    tags=["Source Catalog"],
)


@router.get("/endpoints")
def endpoints():
    return ENDPOINTS


@router.get("/schemas")
def schemas():
    return {
        "count": len(SWAGGER_SCHEMA_NAMES),
        "schemas": SWAGGER_SCHEMA_NAMES,
        "note": (
            "Schema names are from the provided Swagger PDF. "
            "Expanded field definitions were not visible in the PDF."
        ),
    }
