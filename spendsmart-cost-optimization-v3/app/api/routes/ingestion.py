from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import IngestionRun
from app.services.processing.ec2_processor import (
    replace_amis,
    replace_lifecycle,
    upsert_instances,
)
from app.services.spendsmart.compute.ec2 import (
    get_ec2_amis,
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
from app.services.spendsmart.raw_writer import write_raw_json


router = APIRouter(
    prefix="/ingestion",
    tags=["EC2 Ingestion"],
)


@router.post("/ec2")
def ingest_ec2(
    db: Session = Depends(get_db),
):
    run = IngestionRun(
        source="spendsmart",
        dataset="ec2",
        status="started",
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        bundle = {
            "ec2_summary": get_ec2_summary(),
            "ec2_instances": get_ec2_instances(),
            "ec2_lifecycle": get_ec2_lifecycle(),
            "ec2_amis": get_ec2_amis(),
        }

        # Additional source evidence; not normalized into non-EC2 tables.
        try:
            bundle["ec2_optimizations"] = get_ec2_optimizations()
        except Exception as exc:
            bundle["ec2_optimizations_error"] = str(exc)

        try:
            bundle["optimization_summary"] = get_optimization_summary()
        except Exception as exc:
            bundle["optimization_summary_error"] = str(exc)

        try:
            bundle["recommendations"] = get_recommendations()
        except Exception as exc:
            bundle["recommendations_error"] = str(exc)

        try:
            bundle["recommendation_summary"] = get_recommendation_summary()
        except Exception as exc:
            bundle["recommendation_summary_error"] = str(exc)

        raw_path = write_raw_json(
            "ec2",
            bundle,
        )

        instance_count = upsert_instances(
            db,
            bundle["ec2_instances"],
        )

        lifecycle_count = replace_lifecycle(
            db,
            bundle["ec2_lifecycle"],
        )

        ami_count = replace_amis(
            db,
            bundle["ec2_amis"],
        )

        run.status = "success"
        run.records = (
            instance_count
            + lifecycle_count
            + ami_count
        )
        run.raw_path = raw_path
        run.completed_at = datetime.utcnow()

        db.commit()

        return {
            "run_id": run.id,
            "status": run.status,
            "instances": instance_count,
            "lifecycle_records": lifecycle_count,
            "amis": ami_count,
            "raw_path": raw_path,
        }

    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.utcnow()
        db.commit()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
