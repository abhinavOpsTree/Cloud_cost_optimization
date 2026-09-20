from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("ec2_filter")


def _to_float(value: Any, default: float | None = None) -> float | None:
    """
    Safely convert values to float.
    """

    if value is None:
        return default

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return default

        value = value.replace("%", "")

    try:
        return float(value)

    except (TypeError, ValueError):
        logger.warning(
            "Unable to convert value to float | value=%s",
            value,
        )
        return default


def clean_ec2_resources(
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Clean normalized EC2 resources before filtering.
    """

    logger.info(
        "Starting EC2 cleaning | input_records=%s",
        len(resources),
    )

    cleaned_resources: list[dict[str, Any]] = []
    seen_instances: set[str] = set()

    removed_missing_id = 0
    removed_duplicates = 0
    removed_invalid_cost = 0

    for resource in resources:

        instance_id = resource.get("instance_id")

        # --------------------------------
        # Missing instance ID
        # --------------------------------
        if not instance_id:
            removed_missing_id += 1

            logger.warning(
                "Removing EC2 resource | reason=missing_instance_id"
            )

            continue

        instance_id = str(instance_id).strip()

        if not instance_id:
            removed_missing_id += 1

            logger.warning(
                "Removing EC2 resource | reason=empty_instance_id"
            )

            continue

        account_id = str(resource.get("account_id") or "")
        region = str(resource.get("region") or "")

        unique_key = f"{account_id}:{region}:{instance_id}"

        # --------------------------------
        # Duplicate resource
        # --------------------------------
        if unique_key in seen_instances:
            removed_duplicates += 1

            logger.info(
                "Removing duplicate EC2 resource | instance_id=%s | region=%s",
                instance_id,
                region,
            )

            continue

        seen_instances.add(unique_key)

        item = dict(resource)

        item["instance_id"] = instance_id

        # --------------------------------
        # Normalize state
        # --------------------------------
        state = item.get("state")

        if state:
            item["state"] = str(state).strip().lower()

        # --------------------------------
        # Numeric normalization
        # --------------------------------
        item["cpu_utilization_pct"] = _to_float(
            item.get("cpu_utilization_pct")
        )

        item["memory_utilization_pct"] = _to_float(
            item.get("memory_utilization_pct")
        )

        item["monthly_cost"] = _to_float(
            item.get("monthly_cost"),
            0.0,
        )

        item["estimated_monthly_savings"] = _to_float(
            item.get("estimated_monthly_savings"),
            0.0,
        )

        # --------------------------------
        # Invalid negative cost
        # --------------------------------
        if (
            item["monthly_cost"] is not None
            and item["monthly_cost"] < 0
        ):
            removed_invalid_cost += 1

            logger.warning(
                "Removing EC2 resource | instance_id=%s | reason=negative_cost | cost=%s",
                instance_id,
                item["monthly_cost"],
            )

            continue

        cleaned_resources.append(item)

        logger.debug(
            "EC2 resource cleaned | instance_id=%s | state=%s | cpu=%s | memory=%s | monthly_cost=%s",
            instance_id,
            item.get("state"),
            item.get("cpu_utilization_pct"),
            item.get("memory_utilization_pct"),
            item.get("monthly_cost"),
        )

    logger.info(
        (
            "EC2 cleaning completed | input=%s | output=%s | "
            "missing_id=%s | duplicates=%s | invalid_cost=%s"
        ),
        len(resources),
        len(cleaned_resources),
        removed_missing_id,
        removed_duplicates,
        removed_invalid_cost,
    )

    return cleaned_resources


def evaluate_ec2_resource(
    resource: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Evaluate a single EC2 instance using deterministic rules.
    """

    instance_id = resource.get("instance_id")

    cpu = resource.get("cpu_utilization_pct")
    memory = resource.get("memory_utilization_pct")
    monthly_cost = resource.get("monthly_cost") or 0.0
    state = str(resource.get("state") or "").lower()

    logger.debug(
        "Evaluating EC2 resource | instance_id=%s | state=%s | cpu=%s | memory=%s | cost=%s",
        instance_id,
        state,
        cpu,
        memory,
        monthly_cost,
    )

    reasons: list[str] = []

    rule_name = None
    priority = "low"

    # --------------------------------
    # Rule 1: stopped instance
    # --------------------------------
    if state == "stopped":

        rule_name = "stopped_instance"

        reasons.append(
            "EC2 instance is stopped and should be reviewed "
            "for continued business requirement."
        )

        priority = "high" if monthly_cost > 0 else "medium"

        logger.info(
            "EC2 candidate matched | instance_id=%s | rule=%s | priority=%s",
            instance_id,
            rule_name,
            priority,
        )

    # --------------------------------
    # Rule 2: very low CPU
    # --------------------------------
    elif cpu is not None and cpu < 10:

        rule_name = "very_low_cpu"

        reasons.append(
            f"CPU utilization is very low ({cpu:.2f}%)."
        )

        priority = "high"

        logger.info(
            "EC2 candidate matched | instance_id=%s | rule=%s | cpu=%s | priority=%s",
            instance_id,
            rule_name,
            cpu,
            priority,
        )

    # --------------------------------
    # Rule 3: low CPU
    # --------------------------------
    elif cpu is not None and cpu < 20:

        rule_name = "low_cpu"

        reasons.append(
            f"CPU utilization is low ({cpu:.2f}%)."
        )

        priority = "medium"

        logger.info(
            "EC2 candidate matched | instance_id=%s | rule=%s | cpu=%s | priority=%s",
            instance_id,
            rule_name,
            cpu,
            priority,
        )

    else:
        logger.debug(
            "EC2 resource skipped | instance_id=%s | reason=no_optimization_rule_matched",
            instance_id,
        )

        return None

    # --------------------------------
    # Extra memory evidence
    # --------------------------------
    if memory is not None and memory < 20:

        reasons.append(
            f"Memory utilization is also low ({memory:.2f}%)."
        )

        logger.debug(
            "Additional evidence found | instance_id=%s | low_memory=%s",
            instance_id,
            memory,
        )

    # --------------------------------
    # Extra cost evidence
    # --------------------------------
    if monthly_cost >= 100:

        reasons.append(
            f"Monthly cost is relatively high ({monthly_cost:.2f})."
        )

        logger.debug(
            "Additional evidence found | instance_id=%s | high_monthly_cost=%s",
            instance_id,
            monthly_cost,
        )

    candidate = dict(resource)

    candidate["filter_rule"] = rule_name
    candidate["filter_priority"] = priority
    candidate["filter_reasons"] = reasons

    return candidate


def filter_ec2_candidates(
    resources: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Clean, evaluate, rank and return top EC2 candidates.
    """

    logger.info(
        "Starting EC2 candidate filtering | input_records=%s | limit=%s",
        len(resources),
        limit,
    )

    cleaned_resources = clean_ec2_resources(resources)

    logger.info(
        "EC2 cleaning stage finished | cleaned_records=%s",
        len(cleaned_resources),
    )

    candidates: list[dict[str, Any]] = []

    for resource in cleaned_resources:

        candidate = evaluate_ec2_resource(resource)

        if candidate:
            candidates.append(candidate)

    logger.info(
        "EC2 rule evaluation finished | matched_candidates=%s",
        len(candidates),
    )

    # --------------------------------
    # Rank candidates
    # --------------------------------
    candidates.sort(
        key=lambda item: (
            item.get("estimated_monthly_savings") or 0.0,
            item.get("monthly_cost") or 0.0,
        ),
        reverse=True,
    )

    selected_candidates = candidates[:limit]

    logger.info(
        "EC2 candidate filtering completed | total_candidates=%s | selected=%s",
        len(candidates),
        len(selected_candidates),
    )

    for index, candidate in enumerate(
        selected_candidates,
        start=1,
    ):

        logger.info(
            (
                "Selected EC2 candidate | rank=%s | instance_id=%s | "
                "rule=%s | priority=%s | cpu=%s | cost=%s | savings=%s"
            ),
            index,
            candidate.get("instance_id"),
            candidate.get("filter_rule"),
            candidate.get("filter_priority"),
            candidate.get("cpu_utilization_pct"),
            candidate.get("monthly_cost"),
            candidate.get("estimated_monthly_savings"),
        )

    return selected_candidates