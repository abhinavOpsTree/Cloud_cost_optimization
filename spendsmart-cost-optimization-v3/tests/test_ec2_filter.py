from app.services.processing.ec2_filter import (
    clean_ec2_resources,
    filter_ec2_candidates,
)


def test_clean_ec2_resources():

    resources = [
        {
            "instance_id": "i-001",
            "account_id": "123",
            "region": "ap-south-1",
            "state": "RUNNING",
            "cpu_utilization_pct": "8.5",
            "monthly_cost": "250",
        },
        {
            "instance_id": "i-001",
            "account_id": "123",
            "region": "ap-south-1",
            "state": "running",
            "cpu_utilization_pct": "8.5",
            "monthly_cost": "250",
        },
        {
            "instance_id": None,
            "monthly_cost": 100,
        },
    ]

    cleaned = clean_ec2_resources(resources)

    assert len(cleaned) == 1

    assert cleaned[0]["instance_id"] == "i-001"

    assert cleaned[0]["state"] == "running"

    assert cleaned[0]["cpu_utilization_pct"] == 8.5

    assert cleaned[0]["monthly_cost"] == 250.0


def test_filter_ec2_candidates():

    resources = [
        {
            "instance_id": "i-001",
            "account_id": "123",
            "region": "ap-south-1",
            "instance_type": "m5.2xlarge",
            "state": "running",
            "cpu_utilization_pct": 5,
            "memory_utilization_pct": 15,
            "monthly_cost": 300,
            "estimated_monthly_savings": 150,
        },
        {
            "instance_id": "i-002",
            "account_id": "123",
            "region": "ap-south-1",
            "instance_type": "t3.medium",
            "state": "running",
            "cpu_utilization_pct": 55,
            "monthly_cost": 40,
            "estimated_monthly_savings": 0,
        },
        {
            "instance_id": "i-003",
            "account_id": "123",
            "region": "ap-south-1",
            "instance_type": "m5.large",
            "state": "stopped",
            "cpu_utilization_pct": 0,
            "monthly_cost": 80,
            "estimated_monthly_savings": 80,
        },
    ]

    candidates = filter_ec2_candidates(
        resources,
        limit=10,
    )

    assert len(candidates) == 2

    assert candidates[0]["instance_id"] == "i-001"

    assert candidates[0]["filter_rule"] == "very_low_cpu"

    assert candidates[0]["filter_priority"] == "high"