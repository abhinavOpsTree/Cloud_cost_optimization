from fastapi import APIRouter

from app.services.spendsmart.catalog_client import call_catalog_endpoint
from app.services.spendsmart.compute.ec2 import (
    get_ec2_amis,
    get_ec2_instance_metadata,
    get_ec2_instances,
    get_ec2_lifecycle,
    get_ec2_summary,
)
from app.services.spendsmart.optimizations import (
    get_ec2_optimizations,
    get_optimization_summary,
)
from app.services.spendsmart.recommendations import (
    get_recommendations,
    get_recommendation_summary,
)


router = APIRouter(
    prefix="/spendsmart",
    tags=["SpendSmart Source"],
)


@router.get("/health")
def health():
    return call_catalog_endpoint(
        "health",
        "healthz",
    )


@router.get("/ready")
def ready():
    return call_catalog_endpoint(
        "health",
        "readyz",
    )


@router.get("/ec2/summary")
def ec2_summary():
    return get_ec2_summary()


@router.get("/ec2/instances")
def ec2_instances():
    return get_ec2_instances()


@router.get("/ec2/lifecycle")
def ec2_lifecycle():
    return get_ec2_lifecycle()


@router.get("/ec2/amis")
def ec2_amis():
    return get_ec2_amis()


@router.get("/ec2/instances/{instance_id}/metadata")
def ec2_metadata(instance_id: str):
    return get_ec2_instance_metadata(instance_id)


@router.get("/ec2/optimizations")
def ec2_optimizations():
    return get_ec2_optimizations()


@router.get("/optimizations/summary")
def optimizations_summary():
    return get_optimization_summary()


@router.get("/recommendations")
def recommendations():
    return get_recommendations()


@router.get("/recommendations/summary")
def recommendations_summary():
    return get_recommendation_summary()
