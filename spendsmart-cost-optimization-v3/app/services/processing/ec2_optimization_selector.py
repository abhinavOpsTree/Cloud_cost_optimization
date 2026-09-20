from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("ec2_optimization_selector")


SEVERITY_SCORE = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _to_float(
    value: Any,
    default: float = 0.0,
) -> float:
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


def classify_optimization_issue(
    top_issue: str | None,
    instance_state: str | None = None,
) -> str:
    """
    Convert SpendSmart top_issue into a normalized optimization category.
    """

    issue = str(top_issue or "").strip().lower()
    state = str(instance_state or "").strip().lower()

    if state == "stopped" or "stopped instance" in issue:
        return "stopped_resource"

    if "severely over provisioned" in issue:
        return "rightsizing"

    if "over provisioned" in issue:
        return "rightsizing"

    if "savings plan" in issue:
        return "savings_plan"

    if "old-gen" in issue or "old gen" in issue:
        return "generation_upgrade"

    if "graviton" in issue:
        return "graviton"

    if "public ip" in issue:
        return "public_ip"

    if "ebs" in issue or "snapshot" in issue:
        return "storage"

    if "windows" in issue or "license" in issue:
        return "licensing"

    return "other"


def clean_optimization_instance(
    instance: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Validate and normalize one SpendSmart EC2 optimization record.
    """

    instance_id = str(
        instance.get("instance_id") or ""
    ).strip()

    if not instance_id:

        logger.warning(
            "Skipping optimization record | reason=missing_instance_id"
        )

        return None

    item = dict(instance)

    item["instance_id"] = instance_id

    item["instance_name"] = str(
        item.get("instance_name") or ""
    ).strip()

    item["instance_type"] = str(
        item.get("instance_type") or ""
    ).strip()

    item["instance_state"] = str(
        item.get("instance_state") or ""
    ).strip().lower()

    item["region"] = str(
        item.get("region") or ""
    ).strip()

    item["account_name"] = str(
        item.get("account_name") or ""
    ).strip()

    item["severity"] = str(
        item.get("severity") or ""
    ).strip()

    item["top_issue"] = str(
        item.get("top_issue") or ""
    ).strip()

    item["monthly_cost"] = _to_float(
        item.get("monthly_cost")
    )

    item["monthly_savings"] = _to_float(
        item.get("monthly_savings")
    )

    item["saving_pct"] = _to_float(
        item.get("saving_pct")
    )

    item["optimization_type"] = classify_optimization_issue(
        top_issue=item.get("top_issue"),
        instance_state=item.get("instance_state"),
    )

    item["severity_score"] = SEVERITY_SCORE.get(
        item["severity"].lower(),
        0,
    )

    return item


def extract_optimization_instances(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Extract and clean the instances array from the SpendSmart
    EC2 optimization response.
    """

    if not isinstance(response, dict):

        logger.error(
            "Invalid optimization response | expected=dict | received=%s",
            type(response).__name__,
        )

        return []

    raw_instances = response.get("instances", [])

    if not isinstance(raw_instances, list):

        logger.error(
            "Invalid optimization instances | expected=list | received=%s",
            type(raw_instances).__name__,
        )

        return []

    logger.info(
        "Optimization response received | raw_instances=%s",
        len(raw_instances),
    )

    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()

    for instance in raw_instances:

        if not isinstance(instance, dict):
            continue

        item = clean_optimization_instance(instance)

        if not item:
            continue

        instance_id = item["instance_id"]

        if instance_id in seen:

            logger.info(
                "Skipping duplicate optimization | instance_id=%s",
                instance_id,
            )

            continue

        seen.add(instance_id)
        cleaned.append(item)

    logger.info(
        "Optimization records cleaned | raw=%s | cleaned=%s",
        len(raw_instances),
        len(cleaned),
    )

    return cleaned


def select_top_optimization_candidates(
    response: dict[str, Any],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Select the highest-value SpendSmart EC2 optimization candidates.

    Ranking order:
    1. monthly_savings
    2. severity
    3. saving_pct
    4. monthly_cost
    """

    logger.info(
        "Starting optimization candidate selection | limit=%s",
        limit,
    )

    instances = extract_optimization_instances(response)

    candidates = [
        item
        for item in instances
        if item.get("monthly_savings", 0.0) > 0
    ]

    logger.info(
        "Positive-savings candidates found | count=%s",
        len(candidates),
    )

    candidates.sort(
        key=lambda item: (
            item.get("monthly_savings", 0.0),
            item.get("severity_score", 0),
            item.get("saving_pct", 0.0),
            item.get("monthly_cost", 0.0),
        ),
        reverse=True,
    )

    selected = candidates[:limit]

    logger.info(
        "Optimization candidate selection completed | "
        "available=%s | selected=%s",
        len(candidates),
        len(selected),
    )

    for rank, candidate in enumerate(
        selected,
        start=1,
    ):

        logger.info(
            (
                "Optimization candidate selected | "
                "rank=%s | "
                "instance_id=%s | "
                "type=%s | "
                "severity=%s | "
                "cost=%.2f | "
                "savings=%.2f | "
                "saving_pct=%.2f"
            ),
            rank,
            candidate.get("instance_id"),
            candidate.get("optimization_type"),
            candidate.get("severity"),
            candidate.get("monthly_cost", 0.0),
            candidate.get("monthly_savings", 0.0),
            candidate.get("saving_pct", 0.0),
        )

    return selected