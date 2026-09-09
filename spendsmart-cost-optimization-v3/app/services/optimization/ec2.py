from sqlalchemy.orm import Session

from app.models import EC2Instance, OptimizationFinding


def _exists(db, resource_id, finding_type):
    return (
        db.query(OptimizationFinding)
        .filter_by(
            service="EC2",
            resource_id=resource_id,
            finding_type=finding_type,
            status="open",
        )
        .first()
        is not None
    )


def _add(
    db,
    *,
    instance,
    finding_type,
    title,
    description,
    severity,
    savings,
    evidence,
):
    if _exists(
        db,
        instance.instance_id,
        finding_type,
    ):
        return 0

    db.add(
        OptimizationFinding(
            service="EC2",
            resource_id=instance.instance_id,
            finding_type=finding_type,
            title=title,
            description=description,
            severity=severity,
            estimated_monthly_savings=savings,
            evidence=evidence,
            source="local-ec2-rule",
        )
    )

    return 1


def run_rules(db: Session):
    """
    Local fallback analysis.

    Primary source recommendations should come from SpendSmart's optimization
    and recommendation endpoints. These rules only use locally normalized EC2 data.
    """
    created = 0

    for instance in db.query(EC2Instance).all():
        state = (instance.state or "").lower()

        if state in {"stopped", "idle", "inactive"}:
            created += _add(
                db,
                instance=instance,
                finding_type="inactive_instance",
                title="Review inactive EC2 instance",
                description=(
                    "The normalized SpendSmart EC2 inventory indicates that this "
                    "instance is not actively running. Validate ownership and "
                    "dependencies before termination."
                ),
                severity="high",
                savings=float(
                    instance.estimated_monthly_savings
                    or instance.monthly_cost
                    or 0
                ),
                evidence={
                    "state": instance.state,
                    "monthly_cost": instance.monthly_cost,
                },
            )

        if (
            state == "running"
            and instance.cpu_utilization_pct is not None
            and instance.cpu_utilization_pct < 10
        ):
            created += _add(
                db,
                instance=instance,
                finding_type="low_cpu",
                title="Review EC2 instance for rightsizing",
                description=(
                    "Normalized CPU utilization is below 10%. Validate the "
                    "SpendSmart EC2 optimization detail and workload requirements "
                    "before resizing."
                ),
                severity="medium",
                savings=float(
                    instance.estimated_monthly_savings
                    or 0
                ),
                evidence={
                    "cpu_utilization_pct": instance.cpu_utilization_pct,
                    "instance_type": instance.instance_type,
                    "monthly_cost": instance.monthly_cost,
                },
            )

    db.commit()
    return created
