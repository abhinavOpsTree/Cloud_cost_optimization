from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AMIInventory, EC2Instance, EC2Lifecycle, OptimizationFinding
from app.services.analytics.ec2 import summary, top_cost
from app.services.optimization.ec2 import run_rules


router = APIRouter(
    prefix="/ec2",
    tags=["EC2 Processing"],
)


@router.get("/summary")
def local_summary(
    db: Session = Depends(get_db),
):
    return summary(db)


@router.get("/inventory")
def inventory(
    limit: int = 500,
    db: Session = Depends(get_db),
):
    rows = db.query(EC2Instance).limit(limit).all()

    return [
        {
            "account_id": x.account_id,
            "account_name": x.account_name,
            "region": x.region,
            "instance_id": x.instance_id,
            "instance_name": x.instance_name,
            "instance_type": x.instance_type,
            "state": x.state,
            "platform": x.platform,
            "availability_zone": x.availability_zone,
            "cpu_utilization_pct": x.cpu_utilization_pct,
            "memory_utilization_pct": x.memory_utilization_pct,
            "monthly_cost": x.monthly_cost,
            "estimated_monthly_savings": x.estimated_monthly_savings,
        }
        for x in rows
    ]


@router.get("/top-cost")
def top_cost_route(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    return top_cost(db, limit)


@router.get("/lifecycle")
def lifecycle(
    limit: int = 500,
    db: Session = Depends(get_db),
):
    rows = db.query(EC2Lifecycle).limit(limit).all()

    return [
        {
            "instance_id": x.instance_id,
            "lifecycle_state": x.lifecycle_state,
            "launch_time": x.launch_time,
            "age_days": x.age_days,
        }
        for x in rows
    ]


@router.get("/amis")
def amis(
    limit: int = 500,
    db: Session = Depends(get_db),
):
    rows = db.query(AMIInventory).limit(limit).all()

    return [
        {
            "ami_id": x.ami_id,
            "name": x.name,
            "state": x.state,
            "creation_date": x.creation_date,
            "age_days": x.age_days,
            "size_gb": x.size_gb,
        }
        for x in rows
    ]


@router.post("/analysis/run")
def run_analysis(
    db: Session = Depends(get_db),
):
    return {
        "status": "success",
        "findings_created": run_rules(db),
    }


@router.get("/findings")
def findings(
    db: Session = Depends(get_db),
):
    rows = (
        db.query(OptimizationFinding)
        .filter(
            OptimizationFinding.service == "EC2",
            OptimizationFinding.status == "open",
        )
        .order_by(
            OptimizationFinding.estimated_monthly_savings.desc()
        )
        .all()
    )

    return [
        {
            "id": x.id,
            "resource_id": x.resource_id,
            "finding_type": x.finding_type,
            "title": x.title,
            "description": x.description,
            "severity": x.severity,
            "estimated_monthly_savings": x.estimated_monthly_savings,
            "source": x.source,
            "evidence": x.evidence,
        }
        for x in rows
    ]
