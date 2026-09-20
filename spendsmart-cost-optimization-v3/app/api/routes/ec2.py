import logging
from app.core.config import settings
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    AMIInventory,
    EC2Instance,
    EC2Lifecycle,
    OptimizationFinding,
)

from app.services.analytics.ec2 import (
    summary,
    top_cost,
)

from app.services.optimization.ec2 import (
    run_rules,
)

from app.services.processing.ec2_candidate_pipeline import (
    run_ec2_candidate_pipeline,
)
from app.services.ai.ec2 import (
    generate_candidate_recommendations,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("ec2_api")


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/ec2",
    tags=["EC2 Processing"],
)


# ============================================================
# HELPER FUNCTION
# ============================================================

def _ec2_instance_to_dict(
    x: EC2Instance,
) -> dict:
    """
    Convert SQLAlchemy EC2Instance object into dictionary.

    This helper is still used by local database endpoints
    such as /inventory.
    """

    return {
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
        "estimated_monthly_savings": (
            x.estimated_monthly_savings
        ),
    }


# ============================================================
# EC2 SUMMARY
# ============================================================

@router.get("/summary")
def local_summary(
    db: Session = Depends(get_db),
):
    """
    Return summarized EC2 information from local database.

    Example information:
    - total instances
    - running instances
    - stopped instances
    - total monthly cost
    - potential savings
    """

    logger.info(
        "EC2 summary request received"
    )

    result = summary(db)

    logger.info(
        "EC2 summary request completed"
    )

    return result


# ============================================================
# EC2 INVENTORY
# ============================================================

@router.get("/inventory")
def inventory(
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description=(
            "Maximum number of EC2 instances to return"
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Return normalized EC2 inventory stored in local database.

    This data is populated after SpendSmart/UnitEconPro
    EC2 ingestion.
    """

    logger.info(
        "Fetching EC2 inventory | limit=%s",
        limit,
    )

    rows = (
        db.query(EC2Instance)
        .limit(limit)
        .all()
    )

    logger.info(
        "EC2 inventory fetched | records=%s",
        len(rows),
    )

    resources = [
        _ec2_instance_to_dict(x)
        for x in rows
    ]

    logger.info(
        "EC2 inventory response prepared | records=%s",
        len(resources),
    )

    return resources


# ============================================================
# EC2 OPTIMIZATION CANDIDATES
# ============================================================

@router.get("/candidates")
def candidates(
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
        description=(
            "Number of final EC2 optimization "
            "candidates to return"
        ),
    ),
    shortlist_limit: int = Query(
        default=30,
        ge=1,
        le=100,
        description=(
            "Number of native SpendSmart optimization "
            "candidates to enrich and validate before "
            "final selection"
        ),
    ),
):
    """
    Return validated EC2 optimization candidates.

    Processing flow:
    ----------------
    SpendSmart native EC2 optimizations
            ↓
    Rank by estimated monthly savings
            ↓
    Select shortlist
            ↓
    Fetch detailed EC2 metadata
            ↓
    Validate recommendation evidence
            ↓
    Apply safety/context checks
            ↓
    Final ranking
            ↓
    Return Top N candidates

    Validation evidence includes:
    -----------------------------
    - CPU average
    - CPU P95
    - CPU maximum
    - Network throughput
    - Utilization window
    - SpendSmart rightsizing signal
    - Criticality
    - Pricing model
    - EKS membership
    - Auto Scaling Group membership
    - Storage/network context
    - Cost signals

    Important:
    ----------
    This endpoint does not resize, stop, terminate,
    or otherwise modify AWS resources.

    It only identifies and validates optimization
    opportunities.

    No LLM is used at this stage.
    """

    logger.info(
        (
            "Starting EC2 candidate API pipeline | "
            "shortlist_limit=%s | "
            "final_limit=%s"
        ),
        shortlist_limit,
        limit,
    )

    # --------------------------------------------------------
    # STEP 1: Ensure shortlist is not smaller than final limit
    # --------------------------------------------------------

    if shortlist_limit < limit:

        logger.info(
            (
                "Adjusting shortlist_limit | "
                "requested_shortlist=%s | "
                "final_limit=%s"
            ),
            shortlist_limit,
            limit,
        )

        shortlist_limit = limit

    # --------------------------------------------------------
    # STEP 2: Run deterministic EC2 candidate pipeline
    # --------------------------------------------------------

    try:

        result = run_ec2_candidate_pipeline(
            shortlist_limit=shortlist_limit,
            final_limit=limit,
        )

    except Exception:

        logger.exception(
            "EC2 candidate pipeline failed"
        )

        raise

    # --------------------------------------------------------
    # STEP 3: Add API-level information
    # --------------------------------------------------------

    result["candidate_limit"] = limit

    result["shortlist_limit"] = shortlist_limit

    result["next_processing_step"] = (
        "LLM / Recommendation Agent"
    )

    # --------------------------------------------------------
    # STEP 4: Log pipeline summary
    # --------------------------------------------------------

    logger.info(
        (
            "EC2 candidate API pipeline completed | "
            "native=%s | "
            "shortlisted=%s | "
            "metadata_success=%s | "
            "metadata_failed=%s | "
            "validated=%s | "
            "review_required=%s | "
            "returned=%s | "
            "monthly_savings=%s"
        ),
        result.get(
            "native_optimization_count"
        ),
        result.get(
            "shortlist_count"
        ),
        result.get(
            "metadata_success_count"
        ),
        result.get(
            "metadata_failed_count"
        ),
        result.get(
            "validated_count"
        ),
        result.get(
            "review_required_count"
        ),
        result.get(
            "final_candidate_count"
        ),
        result.get(
            "estimated_monthly_savings"
        ),
    )

    return result


# ============================================================
# EC2 AI RECOMMENDATIONS
# ============================================================

@router.post("/recommendations")
def recommendations(
    limit: int = Query(
        default=3,
        ge=1,
        le=10,
        description=(
            "Number of final EC2 candidates for which "
            "LLM recommendations will be generated"
        ),
    ),
    shortlist_limit: int = Query(
        default=5,
        ge=1,
        le=30,
        description=(
            "Number of native SpendSmart optimization "
            "candidates to enrich and validate"
        ),
    ),
):
    """
    Generate AI-assisted recommendations for validated
    EC2 optimization candidates.

    Processing flow:
    ----------------
    SpendSmart native optimizations
            ↓
    Deterministic candidate selection
            ↓
    Metadata enrichment
            ↓
    Rule-based validation
            ↓
    Final candidate ranking
            ↓
    Recommendation Agent

    Important:
    ----------
    The LLM does not select candidates, calculate savings,
    modify ranking, or change validation status.

    It only explains the already-selected optimization
    opportunity and provides implementation guidance.

    This endpoint does not modify AWS resources.
    """

    logger.info(
        (
            "Starting EC2 recommendation API pipeline | "
            "shortlist_limit=%s | "
            "final_limit=%s"
        ),
        shortlist_limit,
        limit,
    )

    # --------------------------------------------------------
    # STEP 1: Ensure shortlist can satisfy final limit
    # --------------------------------------------------------

    if shortlist_limit < limit:

        logger.info(
            (
                "Adjusting recommendation shortlist_limit | "
                "requested_shortlist=%s | "
                "final_limit=%s"
            ),
            shortlist_limit,
            limit,
        )

        shortlist_limit = limit

    # --------------------------------------------------------
    # STEP 2: Run deterministic pipeline
    # --------------------------------------------------------

    try:

        pipeline_result = run_ec2_candidate_pipeline(
            shortlist_limit=shortlist_limit,
            final_limit=limit,
        )

    except Exception:

        logger.exception(
            "EC2 deterministic recommendation pipeline failed"
        )

        raise

    candidates = pipeline_result.get(
        "candidates",
        [],
    )

    # --------------------------------------------------------
    # STEP 3: Generate LLM recommendations
    # --------------------------------------------------------

    logger.info(
        (
            "Sending EC2 candidates to recommendation agent | "
            "candidates=%s"
        ),
        len(candidates),
    )

    recommendations = (
        generate_candidate_recommendations(
            candidates
        )
    )

    # --------------------------------------------------------
    # STEP 4: Recommendation statistics
    # --------------------------------------------------------

    llm_success_count = sum(
        1
        for item in recommendations
        if item.get("llm_used")
    )

    llm_failed_count = (
        len(recommendations)
        - llm_success_count
    )

    # --------------------------------------------------------
    # STEP 5: Build API response
    # --------------------------------------------------------

    result = {
        "status": "success",
        "processing_scope": "EC2 only",
        "source": (
            "SpendSmart native EC2 optimizations "
            "+ metadata validation "
            "+ recommendation agent"
        ),

        "llm_used": (
            llm_success_count > 0
        ),

        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,

        "native_optimization_count": (
            pipeline_result.get(
                "native_optimization_count"
            )
        ),

        "shortlist_count": (
            pipeline_result.get(
                "shortlist_count"
            )
        ),

        "metadata_success_count": (
            pipeline_result.get(
                "metadata_success_count"
            )
        ),

        "metadata_failed_count": (
            pipeline_result.get(
                "metadata_failed_count"
            )
        ),

        "validated_count": (
            pipeline_result.get(
                "validated_count"
            )
        ),

        "review_required_count": (
            pipeline_result.get(
                "review_required_count"
            )
        ),

        "final_candidate_count": len(
            recommendations
        ),

        "llm_success_count": (
            llm_success_count
        ),

        "llm_failed_count": (
            llm_failed_count
        ),

        "estimated_monthly_savings": (
            pipeline_result.get(
                "estimated_monthly_savings"
            )
        ),

        "estimated_annual_savings": (
            pipeline_result.get(
                "estimated_annual_savings"
            )
        ),

        "recommendations": recommendations,
    }

    logger.info(
        (
            "EC2 recommendation API pipeline completed | "
            "candidates=%s | "
            "llm_success=%s | "
            "llm_failed=%s | "
            "monthly_savings=%s"
        ),
        len(recommendations),
        llm_success_count,
        llm_failed_count,
        result.get(
            "estimated_monthly_savings"
        ),
    )

    return result

# ============================================================
# TOP EC2 COST
# ============================================================

@router.get("/top-cost")
def top_cost_route(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description=(
            "Number of highest-cost EC2 instances "
            "to return"
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Return EC2 resources ordered by cost.
    """

    logger.info(
        "Fetching top EC2 cost resources | limit=%s",
        limit,
    )

    result = top_cost(
        db,
        limit,
    )

    logger.info(
        "Top EC2 cost processing completed"
    )

    return result


# ============================================================
# EC2 LIFECYCLE
# ============================================================

@router.get("/lifecycle")
def lifecycle(
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description=(
            "Maximum lifecycle records to return"
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Return EC2 lifecycle information.
    """

    logger.info(
        "Fetching EC2 lifecycle records | limit=%s",
        limit,
    )

    rows = (
        db.query(EC2Lifecycle)
        .limit(limit)
        .all()
    )

    logger.info(
        "EC2 lifecycle records fetched | records=%s",
        len(rows),
    )

    return [
        {
            "instance_id": x.instance_id,
            "lifecycle_state": x.lifecycle_state,
            "launch_time": x.launch_time,
            "age_days": x.age_days,
        }
        for x in rows
    ]


# ============================================================
# AMI INVENTORY
# ============================================================

@router.get("/amis")
def amis(
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description=(
            "Maximum AMI records to return"
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Return AMI inventory related to EC2 processing.
    """

    logger.info(
        "Fetching AMI inventory | limit=%s",
        limit,
    )

    rows = (
        db.query(AMIInventory)
        .limit(limit)
        .all()
    )

    logger.info(
        "AMI inventory fetched | records=%s",
        len(rows),
    )

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


# ============================================================
# RUN LOCAL EC2 ANALYSIS
# ============================================================

@router.post("/analysis/run")
def run_analysis(
    db: Session = Depends(get_db),
):
    """
    Execute existing deterministic EC2 optimization rules.

    This is separate from the new SpendSmart candidate pipeline.

    Existing run_rules() may create OptimizationFinding records.
    """

    logger.info(
        "Starting EC2 optimization analysis"
    )

    findings_created = run_rules(db)

    logger.info(
        (
            "EC2 optimization analysis completed | "
            "findings_created=%s"
        ),
        findings_created,
    )

    return {
        "status": "success",
        "findings_created": findings_created,
    }


# ============================================================
# EXISTING OPTIMIZATION FINDINGS
# ============================================================

@router.get("/findings")
def findings(
    db: Session = Depends(get_db),
):
    """
    Return existing open EC2 optimization findings.

    These records come from the OptimizationFinding table.
    """

    logger.info(
        "Fetching open EC2 optimization findings"
    )

    rows = (
        db.query(OptimizationFinding)
        .filter(
            OptimizationFinding.service == "EC2",
            OptimizationFinding.status == "open",
        )
        .order_by(
            OptimizationFinding
            .estimated_monthly_savings
            .desc()
        )
        .all()
    )

    logger.info(
        "EC2 optimization findings fetched | records=%s",
        len(rows),
    )

    return [
        {
            "id": x.id,
            "resource_id": x.resource_id,
            "finding_type": x.finding_type,
            "title": x.title,
            "description": x.description,
            "severity": x.severity,
            "estimated_monthly_savings": (
                x.estimated_monthly_savings
            ),
            "source": x.source,
            "evidence": x.evidence,
        }
        for x in rows
    ]