from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AISummary
from app.services.ai.ec2 import generate_summary


router = APIRouter(
    prefix="/ai",
    tags=["EC2 AI"],
)


@router.post("/ec2-summary")
def create_summary(
    db: Session = Depends(get_db),
):
    row = generate_summary(db)

    return {
        "id": row.id,
        "provider": row.provider,
        "model": row.model,
        "content": row.content,
    }


@router.get("/ec2-summary/latest")
def latest_summary(
    db: Session = Depends(get_db),
):
    row = (
        db.query(AISummary)
        .filter(
            AISummary.summary_type == "ec2"
        )
        .order_by(
            AISummary.created_at.desc()
        )
        .first()
    )

    if not row:
        return {
            "content": "No EC2 AI summary generated yet."
        }

    return {
        "id": row.id,
        "provider": row.provider,
        "model": row.model,
        "content": row.content,
        "created_at": row.created_at,
    }
