from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("ec2_validator")


def _to_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _validate_rightsizing(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a native SpendSmart rightsizing recommendation
    using detailed utilization metadata.
    """

    reasons: list[str] = []
    safety_notes: list[str] = []

    cpu_avg = _to_float(candidate.get("cpu_avg_pct"))
    cpu_p95 = _to_float(candidate.get("cpu_p95_pct"))
    cpu_max = _to_float(candidate.get("cpu_max_pct"))

    net_in = _to_float(candidate.get("net_in_mbps"))
    net_out = _to_float(candidate.get("net_out_mbps"))

    utilization_days = candidate.get("utilization_days")

    rightsizing_signal = str(
        candidate.get("rightsizing_signal") or ""
    ).upper()

    criticality = str(
        candidate.get("criticality") or ""
    )

    is_eks = bool(candidate.get("is_eks_node"))
    is_asg = bool(candidate.get("is_asg_member"))

    # --------------------------------
    # Native rightsizing evidence
    # --------------------------------

    if rightsizing_signal in {
        "SEVERELY_OVER_PROVISIONED",
        "OVER_PROVISIONED",
        "UNDERUTILIZED",
    }:
        reasons.append(
            f"SpendSmart metadata confirms rightsizing signal: "
            f"{rightsizing_signal}."
        )

    elif rightsizing_signal == "OPTIMIZED":
        safety_notes.append(
            "Optimization conflict: candidate endpoint recommends "
            "rightsizing but metadata reports OPTIMIZED."
        )

        return {
            "validation_status": "review_required",
            "validation_reasons": reasons,
            "safety_notes": safety_notes,
        }

    # --------------------------------
    # CPU P95
    # --------------------------------

    if cpu_p95 is not None:

        if cpu_p95 < 20:
            reasons.append(
                f"CPU P95 is low ({cpu_p95:.2f}%)."
            )

        elif cpu_p95 < 40:
            reasons.append(
                f"CPU P95 is moderate ({cpu_p95:.2f}%)."
            )

            safety_notes.append(
                "Validate target instance capacity before downsizing."
            )

        else:
            safety_notes.append(
                f"CPU P95 is relatively high ({cpu_p95:.2f}%)."
            )

            return {
                "validation_status": "review_required",
                "validation_reasons": reasons,
                "safety_notes": safety_notes,
            }

    else:
        safety_notes.append(
            "CPU P95 is unavailable."
        )

    # --------------------------------
    # CPU maximum
    # --------------------------------

    if cpu_max is not None:

        if cpu_max >= 80:
            safety_notes.append(
                f"CPU maximum reached {cpu_max:.2f}%; "
                "peak workload capacity must be reviewed."
            )

        elif cpu_max >= 50:
            safety_notes.append(
                f"CPU maximum reached {cpu_max:.2f}%; "
                "verify peak workload behavior before resizing."
            )

        else:
            reasons.append(
                f"CPU maximum remained below 50% "
                f"({cpu_max:.2f}%)."
            )

    # --------------------------------
    # CPU average
    # --------------------------------

    if cpu_avg is not None and cpu_avg < 20:
        reasons.append(
            f"CPU average is low ({cpu_avg:.2f}%)."
        )

    # --------------------------------
    # Observation window
    # --------------------------------

    if utilization_days is not None:

        try:
            days = int(utilization_days)

            if days >= 30:
                reasons.append(
                    f"Utilization evidence covers {days} days."
                )

            elif days < 14:
                safety_notes.append(
                    f"Utilization window is only {days} days."
                )

        except (TypeError, ValueError):
            pass

    # --------------------------------
    # Network context
    # --------------------------------

    if (
        (net_in is not None and net_in >= 500)
        or
        (net_out is not None and net_out >= 500)
    ):
        safety_notes.append(
            "High network throughput detected; network capacity "
            "must be considered when selecting a smaller instance type."
        )

    # --------------------------------
    # EKS / ASG safety
    # --------------------------------

    if is_eks:
        safety_notes.append(
            "Instance is an EKS worker node. Apply rightsizing at "
            "the EKS node group / launch template level rather than "
            "resizing this individual managed node."
        )

    if is_asg:
        safety_notes.append(
            "Instance belongs to an Auto Scaling Group. Validate "
            "the ASG launch template and scaling configuration."
        )

    # --------------------------------
    # Criticality
    # --------------------------------

    if criticality:
        reasons.append(
            f"SpendSmart criticality classification: {criticality}."
        )

    return {
        "validation_status": "validated",
        "validation_reasons": reasons,
        "safety_notes": safety_notes,
    }


def _validate_savings_plan(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate Savings Plan opportunities.

    CPU thresholds should not be used to reject commitment
    recommendations.
    """

    reasons: list[str] = []
    safety_notes: list[str] = []

    pricing_model = candidate.get("pricing_model")
    criticality = candidate.get("criticality")

    if pricing_model:
        reasons.append(
            f"Current pricing model: {pricing_model}."
        )

    if criticality:
        reasons.append(
            f"Workload criticality: {criticality}."
        )

    reasons.append(
        "SpendSmart identified a Savings Plan opportunity."
    )

    safety_notes.append(
        "Validate long-term workload continuity and commitment "
        "coverage before purchasing a Savings Plan."
    )

    return {
        "validation_status": "validated",
        "validation_reasons": reasons,
        "safety_notes": safety_notes,
    }


def _validate_stopped_resource(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate stopped-instance / EBS cost opportunities.
    """

    reasons: list[str] = []
    safety_notes: list[str] = []

    state = str(
        candidate.get("instance_state")
        or candidate.get("inferred_state")
        or ""
    ).lower()

    if "stopped" in state:
        reasons.append(
            "Instance is stopped but continues to generate cost."
        )
    else:
        reasons.append(
            "SpendSmart identified stopped-resource related savings."
        )

    attached_ebs = candidate.get("attached_ebs_count")

    if attached_ebs is not None:
        reasons.append(
            f"Attached EBS volumes: {attached_ebs}."
        )

    safety_notes.append(
        "Do not automatically terminate the instance or delete "
        "volumes. Validate rollback, backup, retention and business "
        "requirements first."
    )

    return {
        "validation_status": "validated",
        "validation_reasons": reasons,
        "safety_notes": safety_notes,
    }


def _validate_generation_upgrade(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate old-generation instance modernization opportunities.
    """

    reasons: list[str] = []
    safety_notes: list[str] = []

    instance_type = candidate.get("instance_type")
    architecture = candidate.get("architecture")
    platform = candidate.get("platform")

    reasons.append(
        "SpendSmart identified an older-generation EC2 instance."
    )

    if instance_type:
        reasons.append(
            f"Current instance type: {instance_type}."
        )

    if architecture:
        reasons.append(
            f"Architecture: {architecture}."
        )

    if platform:
        reasons.append(
            f"Platform: {platform}."
        )

    safety_notes.append(
        "Validate application, AMI, driver and architecture "
        "compatibility before migrating to a newer generation."
    )

    return {
        "validation_status": "validated",
        "validation_reasons": reasons,
        "safety_notes": safety_notes,
    }


def validate_ec2_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate one enriched EC2 optimization candidate.
    """

    result = dict(candidate)

    optimization_type = str(
        candidate.get("optimization_type") or "other"
    )

    # Metadata is particularly important for rightsizing.
    if (
        optimization_type == "rightsizing"
        and not candidate.get("metadata_available")
    ):
        result["validation_status"] = "review_required"
        result["validation_reasons"] = [
            "Native SpendSmart optimization exists."
        ]
        result["safety_notes"] = [
            "Detailed EC2 metadata could not be retrieved. "
            "Rightsizing should not proceed without utilization validation."
        ]

        return result

    if optimization_type == "rightsizing":
        validation = _validate_rightsizing(candidate)

    elif optimization_type == "savings_plan":
        validation = _validate_savings_plan(candidate)

    elif optimization_type == "stopped_resource":
        validation = _validate_stopped_resource(candidate)

    elif optimization_type == "generation_upgrade":
        validation = _validate_generation_upgrade(candidate)

    else:
        validation = {
            "validation_status": "review_required",
            "validation_reasons": [
                "SpendSmart optimization was detected."
            ],
            "safety_notes": [
                "No specialized validation rule exists for "
                f"optimization type: {optimization_type}."
            ],
        }

    result.update(validation)

    logger.info(
        (
            "EC2 candidate validated | "
            "instance_id=%s | "
            "type=%s | "
            "status=%s | "
            "savings=%s"
        ),
        result.get("instance_id"),
        optimization_type,
        result.get("validation_status"),
        result.get("monthly_savings"),
    )

    return result


def validate_ec2_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate all enriched EC2 candidates.
    """

    logger.info(
        "Starting EC2 candidate validation | candidates=%s",
        len(candidates),
    )

    validated: list[dict[str, Any]] = []

    for candidate in candidates:
        validated.append(
            validate_ec2_candidate(candidate)
        )

    logger.info(
        "EC2 candidate validation completed | candidates=%s",
        len(validated),
    )

    return validated
