"""
EC2-only normalization.

The provided Swagger PDF names EC2 schemas:
- EC2Instance
- EC2InstanceMetadata
- EC2LifecycleInstance
- EC2Summary
- EC2Gap

but does not expose their full properties.

Until /openapi.json is supplied, this normalizer supports common aliases
without claiming that those aliases are the official schema fields.
"""


def first(row: dict, *keys, default=None):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def as_float(value, default=None):
    if value in (None, ""):
        return default

    if isinstance(value, str):
        value = (
            value
            .replace(",", "")
            .replace("$", "")
            .replace("%", "")
            .strip()
        )

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_rows(payload, preferred=()):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    keys = preferred + (
        "data",
        "items",
        "results",
        "records",
        "instances",
        "rows",
    )

    for key in keys:
        value = payload.get(key)

        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

        if isinstance(value, dict):
            for nested_key in keys:
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [x for x in nested if isinstance(x, dict)]

    return []


def normalize_instance(row: dict):
    return {
        "account_id": str(first(
            row,
            "account_id", "accountId",
            default="unknown",
        )),
        "account_name": first(
            row,
            "account_name", "accountName", "account",
        ),
        "region": str(first(
            row,
            "region", "aws_region", "awsRegion",
            default="unknown",
        )),
        "instance_id": str(first(
            row,
            "instance_id", "instanceId", "id",
            default="unknown",
        )),
        "instance_name": first(
            row,
            "instance_name", "instanceName", "name",
        ),
        "instance_type": first(
            row,
            "instance_type", "instanceType", "type",
        ),
        "state": first(
            row,
            "state", "status", "instance_state", "instanceState",
        ),
        "platform": first(
            row,
            "platform", "os", "operating_system", "operatingSystem",
        ),
        "availability_zone": first(
            row,
            "availability_zone", "availabilityZone", "az",
        ),
        "vpc_id": first(row, "vpc_id", "vpcId"),
        "subnet_id": first(row, "subnet_id", "subnetId"),

        "cpu_utilization_pct": as_float(first(
            row,
            "cpu_utilization_pct",
            "cpuUtilizationPct",
            "cpu_utilization",
            "cpuUtilization",
            "avg_cpu",
            "avgCpu",
        )),

        "memory_utilization_pct": as_float(first(
            row,
            "memory_utilization_pct",
            "memoryUtilizationPct",
            "memory_utilization",
            "memoryUtilization",
            "avg_memory",
            "avgMemory",
        )),

        "monthly_cost": as_float(first(
            row,
            "monthly_cost",
            "monthlyCost",
            "cost",
            "total_cost",
            "totalCost",
        )),

        "estimated_monthly_savings": as_float(first(
            row,
            "estimated_monthly_savings",
            "estimatedMonthlySavings",
            "potential_savings",
            "potentialSavings",
            "savings",
        )),

        "currency": str(first(
            row,
            "currency", "currencyCode",
            default="USD",
        )),

        "lifecycle": first(
            row,
            "lifecycle",
            "purchase_option",
            "purchaseOption",
        ),

        "recommendation": first(
            row,
            "recommendation",
            "recommendation_text",
            "recommendationText",
        ),

        "tags": row.get("tags") if isinstance(row.get("tags"), dict) else None,
        "source_json": row,
    }


def normalize_lifecycle(row: dict):
    return {
        "instance_id": str(first(
            row,
            "instance_id", "instanceId", "id",
            default="unknown",
        )),
        "lifecycle_state": first(
            row,
            "lifecycle_state", "lifecycleState", "state", "status",
        ),
        "launch_time": first(
            row,
            "launch_time", "launchTime", "created_at", "createdAt",
        ),
        "age_days": as_float(first(
            row,
            "age_days", "ageDays", "days_running", "daysRunning",
        )),
        "source_json": row,
    }


def normalize_ami(row: dict):
    return {
        "ami_id": str(first(
            row,
            "ami_id", "amiId", "image_id", "imageId", "id",
            default="unknown",
        )),
        "name": first(row, "name", "ami_name", "amiName"),
        "state": first(row, "state", "status"),
        "creation_date": first(
            row,
            "creation_date", "creationDate", "created_at", "createdAt",
        ),
        "age_days": as_float(first(row, "age_days", "ageDays")),
        "size_gb": as_float(first(row, "size_gb", "sizeGb", "size")),
        "source_json": row,
    }
