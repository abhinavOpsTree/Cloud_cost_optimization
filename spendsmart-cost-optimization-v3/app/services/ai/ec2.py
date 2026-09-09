import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AISummary, OptimizationFinding
from app.services.analytics.ec2 import summary, top_cost


def generate_summary(db: Session):
    context = {
        "source": "SpendSmart / UnitEconPro",
        "service": "EC2",
        "summary": summary(db),
        "top_cost_instances": top_cost(db, 15),
        "local_findings": [
            {
                "resource_id": x.resource_id,
                "finding_type": x.finding_type,
                "title": x.title,
                "severity": x.severity,
                "estimated_monthly_savings": x.estimated_monthly_savings,
                "evidence": x.evidence,
            }
            for x in (
                db.query(OptimizationFinding)
                .filter(
                    OptimizationFinding.service == "EC2",
                    OptimizationFinding.status == "open",
                )
                .limit(15)
                .all()
            )
        ],
    }

    if not settings.enable_llm:
        content = (
            "LLM is disabled. Set ENABLE_LLM=true and configure GROQ_API_KEY."
        )
        provider = "disabled"

    else:
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured")

        from groq import Groq

        client = Groq(
            api_key=settings.groq_api_key.strip()
        )

        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the SpendSmart EC2 FinOps assistant. "
                        "Use only the supplied evidence for account-specific claims. "
                        "Do not invent cost, utilization, savings, resources, or recommendations."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create an EC2 cost optimization executive summary from:\n"
                        + json.dumps(context, default=str)
                    ),
                },
            ],
        )

        content = (
            response.choices[0].message.content
            or ""
        )

        provider = "groq"

    row = AISummary(
        summary_type="ec2",
        provider=provider,
        model=settings.llm_model,
        content=content,
        context_json=context,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return row
