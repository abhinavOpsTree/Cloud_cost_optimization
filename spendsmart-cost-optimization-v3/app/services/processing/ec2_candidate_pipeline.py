from __future__ import annotations

import logging
from typing import Any

from app.services.spendsmart.optimizations import (
    get_ec2_optimizations,
)

from app.services.processing.ec2_optimization_selector import (
    extract_optimization_instances,
    select_top_optimization_candidates,
)

from app.services.processing.ec2_enricher import (
    enrich_ec2_candidates,
)

from app.services.processing.ec2_validator import (
    validate_ec2_candidates,
)


logger = logging.getLogger("ec2_candidate_pipeline")


VALIDATION_PRIORITY = {
    "validated": 2,
    "review_required": 1,
}


def _rank_final_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Rank final candidates.

    Primary financial ranking remains monthly_savings.

    Validation status is used as supporting evidence rather than
    overriding a materially larger savings opportunity.
    """

    return sorted(
        candidates,
        key=lambda item: (
            item.get("monthly_savings") or 0.0,
            VALIDATION_PRIORITY.get(
                str(
                    item.get("validation_status") or ""
                ).lower(),
                0,
            ),
            item.get("severity_score") or 0,
            item.get("saving_pct") or 0.0,
            item.get("monthly_cost") or 0.0,
        ),
        reverse=True,
    )


def run_ec2_candidate_pipeline(
    shortlist_limit: int = 30,
    final_limit: int = 10,
) -> dict[str, Any]:
    """
    Run the complete deterministic EC2 candidate pipeline.

    Flow:

    SpendSmart native optimizations
        ->
    shortlist by native savings
        ->
    metadata enrichment
        ->
    category-specific validation
        ->
    final ranking
        ->
    top candidates

    No LLM is used in this pipeline.
    """

    logger.info(
        (
            "Starting EC2 candidate pipeline | "
            "shortlist_limit=%s | final_limit=%s"
        ),
        shortlist_limit,
        final_limit,
    )

    # -----------------------------------------
    # 1. Fetch native SpendSmart optimizations
    # -----------------------------------------

    optimization_response = get_ec2_optimizations()

    if not isinstance(optimization_response, dict):
        raise ValueError(
            "SpendSmart EC2 optimization response must be a dictionary."
        )

    all_optimization_instances = (
        extract_optimization_instances(
            optimization_response
        )
    )

    logger.info(
        "Native EC2 optimization records | count=%s",
        len(all_optimization_instances),
    )

    # -----------------------------------------
    # 2. Select native shortlist
    # -----------------------------------------

    shortlist = select_top_optimization_candidates(
        optimization_response,
        limit=shortlist_limit,
    )

    logger.info(
        "EC2 optimization shortlist created | count=%s",
        len(shortlist),
    )

    # -----------------------------------------
    # 3. Metadata enrichment
    # -----------------------------------------

    enriched = enrich_ec2_candidates(
        shortlist
    )

    metadata_success = sum(
        1
        for item in enriched
        if item.get("metadata_available")
    )

    metadata_failed = (
        len(enriched) - metadata_success
    )

    logger.info(
        (
            "EC2 enrichment stage completed | "
            "success=%s | failed=%s"
        ),
        metadata_success,
        metadata_failed,
    )

    # -----------------------------------------
    # 4. Validation
    # -----------------------------------------

    validated = validate_ec2_candidates(
        enriched
    )

    validated_count = sum(
        1
        for item in validated
        if item.get("validation_status")
        == "validated"
    )

    review_required_count = sum(
        1
        for item in validated
        if item.get("validation_status")
        == "review_required"
    )

    logger.info(
        (
            "EC2 validation stage completed | "
            "validated=%s | review_required=%s"
        ),
        validated_count,
        review_required_count,
    )

    # -----------------------------------------
    # 5. Final ranking
    # -----------------------------------------

    ranked = _rank_final_candidates(
        validated
    )

    final_candidates = ranked[:final_limit]

    # -----------------------------------------
    # 6. Add final rank
    # -----------------------------------------

    final_output: list[dict[str, Any]] = []

    for rank, candidate in enumerate(
        final_candidates,
        start=1,
    ):

        item = dict(candidate)

        item["final_rank"] = rank

        final_output.append(item)

        logger.info(
            (
                "Final EC2 candidate | "
                "rank=%s | "
                "instance_id=%s | "
                "optimization=%s | "
                "status=%s | "
                "monthly_savings=%s"
            ),
            rank,
            item.get("instance_id"),
            item.get("optimization_type"),
            item.get("validation_status"),
            item.get("monthly_savings"),
        )

    total_monthly_savings = round(
        sum(
            float(
                item.get("monthly_savings") or 0.0
            )
            for item in final_output
        ),
        2,
    )

    total_monthly_cost = round(
        sum(
            float(
                item.get("monthly_cost") or 0.0
            )
            for item in final_output
        ),
        2,
    )

    logger.info(
        (
            "EC2 candidate pipeline completed | "
            "native=%s | "
            "shortlisted=%s | "
            "final=%s | "
            "monthly_savings=%s"
        ),
        len(all_optimization_instances),
        len(shortlist),
        len(final_output),
        total_monthly_savings,
    )

    return {
        "status": "success",

        "processing_scope": "EC2 only",

        "source": "SpendSmart native EC2 optimizations",

        "llm_used": False,

        "native_optimization_count": len(
            all_optimization_instances
        ),

        "shortlist_count": len(shortlist),

        "metadata_success_count": metadata_success,

        "metadata_failed_count": metadata_failed,

        "validated_count": validated_count,

        "review_required_count": review_required_count,

        "final_candidate_count": len(
            final_output
        ),

        "total_monthly_cost": total_monthly_cost,

        "estimated_monthly_savings": (
            total_monthly_savings
        ),

        "estimated_annual_savings": round(
            total_monthly_savings * 12,
            2,
        ),

        "candidates": final_output,
    }