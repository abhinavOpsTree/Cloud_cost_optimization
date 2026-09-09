from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AMIInventory, EC2Instance, EC2Lifecycle, OptimizationFinding


def summary(db: Session):
    total = db.query(EC2Instance).count()

    running = (
        db.query(EC2Instance)
        .filter(func.lower(EC2Instance.state) == "running")
        .count()
    )

    stopped = (
        db.query(EC2Instance)
        .filter(func.lower(EC2Instance.state) == "stopped")
        .count()
    )

    monthly_cost = (
        db.query(
            func.coalesce(
                func.sum(EC2Instance.monthly_cost),
                0,
            )
        )
        .scalar()
        or 0
    )

    savings = (
        db.query(
            func.coalesce(
                func.sum(OptimizationFinding.estimated_monthly_savings),
                0,
            )
        )
        .filter(
            OptimizationFinding.service == "EC2",
            OptimizationFinding.status == "open",
        )
        .scalar()
        or 0
    )

    return {
        "instances": total,
        "running": running,
        "stopped": stopped,
        "monthly_cost": round(float(monthly_cost), 2),
        "potential_monthly_savings": round(float(savings), 2),
        "lifecycle_records": db.query(EC2Lifecycle).count(),
        "ami_count": db.query(AMIInventory).count(),
    }


def top_cost(db: Session, limit=20):
    rows = (
        db.query(EC2Instance)
        .order_by(
            EC2Instance.monthly_cost.desc().nullslast()
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "instance_id": x.instance_id,
            "instance_name": x.instance_name,
            "instance_type": x.instance_type,
            "state": x.state,
            "region": x.region,
            "cpu_utilization_pct": x.cpu_utilization_pct,
            "memory_utilization_pct": x.memory_utilization_pct,
            "monthly_cost": x.monthly_cost,
            "estimated_monthly_savings": x.estimated_monthly_savings,
        }
        for x in rows
    ]
