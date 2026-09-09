from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AMIInventory, EC2Instance, EC2Lifecycle
from app.services.processing.ec2_normalizer import (
    extract_rows,
    normalize_ami,
    normalize_instance,
    normalize_lifecycle,
)


def upsert_instances(db: Session, payload) -> int:
    rows = extract_rows(
        payload,
        ("instances", "ec2_instances", "ec2Instances"),
    )

    count = 0

    for raw in rows:
        row = normalize_instance(raw)

        existing = (
            db.query(EC2Instance)
            .filter_by(
                account_id=row["account_id"],
                region=row["region"],
                instance_id=row["instance_id"],
            )
            .first()
        )

        if existing:
            for key, value in row.items():
                setattr(existing, key, value)

            existing.updated_at = datetime.utcnow()

        else:
            db.add(EC2Instance(**row))

        count += 1

    db.commit()
    return count


def replace_lifecycle(db: Session, payload) -> int:
    rows = extract_rows(
        payload,
        ("lifecycle", "instances"),
    )

    db.query(EC2Lifecycle).delete()

    for raw in rows:
        db.add(
            EC2Lifecycle(
                **normalize_lifecycle(raw)
            )
        )

    db.commit()
    return len(rows)


def replace_amis(db: Session, payload) -> int:
    rows = extract_rows(
        payload,
        ("amis", "images", "inventory"),
    )

    db.query(AMIInventory).delete()

    for raw in rows:
        db.add(
            AMIInventory(
                **normalize_ami(raw)
            )
        )

    db.commit()
    return len(rows)
