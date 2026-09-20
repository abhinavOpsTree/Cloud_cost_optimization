from __future__ import annotations

import logging
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import Any

from app.services.spendsmart.compute.ec2 import (
    get_ec2_instance_metadata,
)


logger = logging.getLogger("ec2_enricher")


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_MAX_WORKERS = 2


# ============================================================
# TYPE CONVERSION HELPERS
# ============================================================

def _to_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    """
    Safely convert a value to float.
    """

    if value is None:
        return default

    if isinstance(value, str):
        value = value.strip().replace("%", "")

        if not value:
            return default

    try:
        return float(value)

    except (TypeError, ValueError):

        logger.warning(
            "Unable to convert value to float | value=%s",
            value,
        )

        return default


def _to_int(
    value: Any,
    default: int | None = None,
) -> int | None:
    """
    Safely convert a value to int.
    """

    if value is None:
        return default

    try:
        return int(value)

    except (TypeError, ValueError):

        logger.warning(
            "Unable to convert value to int | value=%s",
            value,
        )

        return default


# ============================================================
# EKS / ASG HELPERS
# ============================================================

def _detect_eks(
    metadata: dict[str, Any],
) -> bool:
    """
    Detect whether an EC2 instance appears to belong to EKS.
    """

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        tags = {}

    eks_keys = (
        "aws:eks:cluster-name",
        "eks:cluster-name",
        "eks:nodegroup-name",
    )

    for key in eks_keys:

        if tags.get(key):
            return True

    for key in tags:

        normalized_key = str(key).lower()

        if "kubernetes.io/cluster/" in normalized_key:
            return True

        if "cluster-autoscaler" in normalized_key:
            return True

    return False


def _detect_asg(
    metadata: dict[str, Any],
) -> bool:
    """
    Detect whether an EC2 instance belongs to an
    Auto Scaling Group.
    """

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        return False

    return bool(
        tags.get("aws:autoscaling:groupName")
    )


def _get_eks_cluster(
    metadata: dict[str, Any],
) -> str | None:
    """
    Extract EKS cluster name from metadata tags.
    """

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        return None

    return (
        tags.get("aws:eks:cluster-name")
        or tags.get("eks:cluster-name")
    )


def _get_eks_nodegroup(
    metadata: dict[str, Any],
) -> str | None:
    """
    Extract EKS node group name.
    """

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        return None

    return tags.get(
        "eks:nodegroup-name"
    )


def _get_asg_name(
    metadata: dict[str, Any],
) -> str | None:
    """
    Extract Auto Scaling Group name.
    """

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        return None

    return tags.get(
        "aws:autoscaling:groupName"
    )


# ============================================================
# METADATA NORMALIZATION
# ============================================================

def normalize_metadata(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize SpendSmart EC2 metadata fields used by the
    optimization validation pipeline.
    """

    cost_signals = (
        metadata.get("cost_signals") or []
    )

    if not isinstance(cost_signals, list):
        cost_signals = []

    tags = metadata.get("tags") or {}

    if not isinstance(tags, dict):
        tags = {}

    normalized = {

        # ----------------------------------------------------
        # Metadata status
        # ----------------------------------------------------

        "metadata_available": True,

        # ----------------------------------------------------
        # Resource information
        # ----------------------------------------------------

        "availability_zone": metadata.get(
            "availability_zone"
        ),

        "aws_account_id": metadata.get(
            "aws_account_id"
        ),

        "platform": metadata.get(
            "platform"
        ),

        "architecture": metadata.get(
            "architecture"
        ),

        "last_launch_time": metadata.get(
            "last_launch_time"
        ),

        "inferred_state": metadata.get(
            "inferred_state"
        ),

        "terminated_at": metadata.get(
            "terminated_at"
        ),

        # ----------------------------------------------------
        # Pricing / business context
        # ----------------------------------------------------

        "pricing_model": metadata.get(
            "pricing_model"
        ),

        "criticality": metadata.get(
            "criticality"
        ),

        "insight": metadata.get(
            "insight"
        ),

        # ----------------------------------------------------
        # Performance
        # ----------------------------------------------------

        "cpu_avg_pct": _to_float(
            metadata.get("cpu_avg_pct")
        ),

        "cpu_p95_pct": _to_float(
            metadata.get("cpu_p95_pct")
        ),

        "cpu_max_pct": _to_float(
            metadata.get("cpu_max_pct")
        ),

        "net_in_mbps": _to_float(
            metadata.get("net_in_mbps")
        ),

        "net_out_mbps": _to_float(
            metadata.get("net_out_mbps")
        ),

        "utilization_days": _to_int(
            metadata.get("utilization_days")
        ),

        "utilization_updated": metadata.get(
            "utilization_updated"
        ),

        "rightsizing_signal": metadata.get(
            "rightsizing_signal"
        ),

        # ----------------------------------------------------
        # Storage / networking
        # ----------------------------------------------------

        "ebs_optimized": metadata.get(
            "ebs_optimized"
        ),

        "detailed_monitoring": metadata.get(
            "detailed_monitoring"
        ),

        "has_public_ip": metadata.get(
            "has_public_ip"
        ),

        "attached_ebs_count": _to_int(
            metadata.get("attached_ebs_count")
        ),

        "root_volume_type": metadata.get(
            "root_volume_type"
        ),

        "root_volume_size_gb": _to_float(
            metadata.get("root_volume_size_gb")
        ),

        # ----------------------------------------------------
        # AMI
        # ----------------------------------------------------

        "image_id": metadata.get(
            "image_id"
        ),

        "ami_name": metadata.get(
            "ami_name"
        ),

        "ami_state": metadata.get(
            "ami_state"
        ),

        "ami_is_public": metadata.get(
            "ami_is_public"
        ),

        "ami_snapshot_cost_30d": _to_float(
            metadata.get(
                "ami_snapshot_cost_30d"
            ),
            0.0,
        ),

        # ----------------------------------------------------
        # Governance
        # ----------------------------------------------------

        "tags": tags,

        "cost_signals": cost_signals,

        # ----------------------------------------------------
        # Workload context
        # ----------------------------------------------------

        "is_eks_node": _detect_eks(
            metadata
        ),

        "eks_cluster": _get_eks_cluster(
            metadata
        ),

        "eks_nodegroup": _get_eks_nodegroup(
            metadata
        ),

        "is_asg_member": _detect_asg(
            metadata
        ),

        "asg_name": _get_asg_name(
            metadata
        ),
    }

    return normalized


# ============================================================
# SINGLE CANDIDATE ENRICHMENT
# ============================================================

def enrich_ec2_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Enrich one optimization candidate with SpendSmart metadata.

    Metadata failure does not remove the candidate.

    Instead metadata_available=False is returned so that
    the validation layer can decide how to handle it.
    """

    instance_id = candidate.get(
        "instance_id"
    )

    if not instance_id:

        logger.warning(
            (
                "Cannot enrich candidate | "
                "reason=missing_instance_id"
            )
        )

        result = dict(candidate)

        result["metadata_available"] = False

        result["metadata_error"] = (
            "missing_instance_id"
        )

        return result

    logger.info(
        "Fetching EC2 metadata | instance_id=%s",
        instance_id,
    )

    try:

        metadata = get_ec2_instance_metadata(
            str(instance_id)
        )

    except Exception as exc:

        logger.exception(
            (
                "EC2 metadata request failed | "
                "instance_id=%s"
            ),
            instance_id,
        )

        result = dict(candidate)

        result["metadata_available"] = False

        result["metadata_error"] = str(exc)

        return result

    if not isinstance(metadata, dict):

        logger.warning(
            (
                "Invalid EC2 metadata response | "
                "instance_id=%s | "
                "type=%s"
            ),
            instance_id,
            type(metadata).__name__,
        )

        result = dict(candidate)

        result["metadata_available"] = False

        result["metadata_error"] = (
            "metadata_response_is_not_dict"
        )

        return result

    normalized_metadata = normalize_metadata(
        metadata
    )

    # --------------------------------------------------------
    # Candidate remains the canonical source for native
    # optimization information such as:
    #
    # monthly_cost
    # monthly_savings
    # saving_pct
    # severity
    # top_issue
    # optimization_type
    #
    # Metadata only adds supporting evidence.
    # --------------------------------------------------------

    result = dict(candidate)

    result.update(
        normalized_metadata
    )

    logger.info(
        (
            "EC2 metadata enriched | "
            "instance_id=%s | "
            "cpu_avg=%s | "
            "cpu_p95=%s | "
            "cpu_max=%s | "
            "rightsizing_signal=%s | "
            "criticality=%s | "
            "eks=%s | "
            "asg=%s"
        ),
        instance_id,
        result.get("cpu_avg_pct"),
        result.get("cpu_p95_pct"),
        result.get("cpu_max_pct"),
        result.get("rightsizing_signal"),
        result.get("criticality"),
        result.get("is_eks_node"),
        result.get("is_asg_member"),
    )

    return result


# ============================================================
# CONCURRENT CANDIDATE ENRICHMENT
# ============================================================

def enrich_ec2_candidates(
    candidates: list[dict[str, Any]],
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[dict[str, Any]]:
    """
    Enrich multiple EC2 optimization candidates concurrently.

    Important:
    ----------
    ThreadPoolExecutor is appropriate here because metadata
    retrieval is network I/O bound.

    Candidate order is preserved in the returned list even
    though HTTP requests may complete in a different order.
    """

    candidate_count = len(candidates)

    logger.info(
        (
            "Starting concurrent EC2 candidate enrichment | "
            "candidates=%s | max_workers=%s"
        ),
        candidate_count,
        max_workers,
    )

    if candidate_count == 0:

        logger.info(
            "No EC2 candidates supplied for enrichment"
        )

        return []

    # --------------------------------------------------------
    # Prevent invalid or excessive worker count
    # --------------------------------------------------------

    worker_count = max(
        1,
        min(
            max_workers,
            candidate_count,
        ),
    )

    # --------------------------------------------------------
    # Pre-allocate list so original candidate ordering
    # can be preserved.
    # --------------------------------------------------------

    enriched: list[
        dict[str, Any] | None
    ] = [
        None
        for _ in candidates
    ]

    success_count = 0
    failure_count = 0

    # --------------------------------------------------------
    # Execute metadata requests concurrently
    # --------------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:

        future_to_index = {
            executor.submit(
                enrich_ec2_candidate,
                candidate,
            ): index

            for index, candidate
            in enumerate(candidates)
        }

        for future in as_completed(
            future_to_index
        ):

            index = future_to_index[
                future
            ]

            candidate = candidates[
                index
            ]

            instance_id = candidate.get(
                "instance_id"
            )

            try:

                result = future.result()

            except Exception as exc:

                # This is an additional safety layer.
                # enrich_ec2_candidate() already handles
                # metadata request failures internally.

                logger.exception(
                    (
                        "Unexpected enrichment worker "
                        "failure | instance_id=%s"
                    ),
                    instance_id,
                )

                result = dict(candidate)

                result[
                    "metadata_available"
                ] = False

                result[
                    "metadata_error"
                ] = str(exc)

            enriched[index] = result

            if result.get(
                "metadata_available"
            ):
                success_count += 1

            else:
                failure_count += 1

            logger.info(
                (
                    "EC2 enrichment progress | "
                    "completed=%s/%s | "
                    "instance_id=%s | "
                    "metadata_available=%s"
                ),
                (
                    success_count
                    + failure_count
                ),
                candidate_count,
                instance_id,
                result.get(
                    "metadata_available"
                ),
            )

    # --------------------------------------------------------
    # Defensive fallback
    #
    # Every slot should normally contain a result.
    # --------------------------------------------------------

    final_results: list[
        dict[str, Any]
    ] = []

    for index, result in enumerate(
        enriched
    ):

        if result is not None:

            final_results.append(
                result
            )

            continue

        candidate = dict(
            candidates[index]
        )

        candidate[
            "metadata_available"
        ] = False

        candidate[
            "metadata_error"
        ] = "enrichment_result_missing"

        final_results.append(
            candidate
        )

        failure_count += 1

        logger.error(
            (
                "Missing enrichment result | "
                "instance_id=%s"
            ),
            candidate.get(
                "instance_id"
            ),
        )

    logger.info(
        (
            "Concurrent EC2 candidate enrichment completed | "
            "input=%s | "
            "workers=%s | "
            "success=%s | "
            "failed=%s"
        ),
        candidate_count,
        worker_count,
        success_count,
        failure_count,
    )

    return final_results