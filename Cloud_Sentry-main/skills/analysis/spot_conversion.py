"""
skills/analysis/spot_conversion.py
------------------------------------
Spot Conversion Skill — recommends Spot pricing for eligible OnDemand instances.

Applies to all instances where is_spot_eligible == True (94 in pilot).
Saving estimate: 65% of monthly cost.

Pure Python — zero Gemini calls.
"""
from __future__ import annotations

from core.base_skill import BaseAnalysisSkill

SPOT_SAVING_PCT = 65.0


class SpotConversionSkill(BaseAnalysisSkill):
    """Spot conversion recommendations for eligible OnDemand instances."""

    NAME = "spot_conversion"
    DISPLAY_NAME = "Spot Conversion"
    DESCRIPTION = "Recommends Spot pricing for eligible OnDemand instances (65% saving)"
    TRACK = "spot"
    VERSION = "1.0.0"

    def can_apply(self, instance: dict) -> bool:
        """Only applies to Spot-eligible instances."""
        return instance.get("is_spot_eligible") == True

    def analyse(self, instance: dict) -> dict:
        """All Spot-eligible instances get a recommendation."""
        monthly_cost = instance.get("monthly_cost_est", 0.0) or 0.0
        if monthly_cost <= 0:
            return {}

        name = str(instance.get("resource_name", "")).lower()

        # Determine confidence based on name patterns
        safe_patterns = ["test", "testing", "staging", "batch", "worker",
                         "dev", "demo", "experiment", "benchmark"]
        risky_patterns = ["main", "primary", "prod", "vpn", "proxy",
                          "master", "core", "critical"]

        confidence = 0.80  # default
        flag_review = False

        for pat in safe_patterns:
            if pat in name:
                confidence = 0.90
                break
        for pat in risky_patterns:
            if pat in name:
                confidence = 0.60
                flag_review = True
                break

        return {
            "monthly_cost": monthly_cost,
            "confidence": confidence,
            "flag_review": flag_review,
        }

    def recommend(self, instance: dict, finding: dict) -> dict | None:
        """Convert finding to Spot recommendation."""
        if not finding or not finding.get("monthly_cost"):
            return None

        monthly_cost = finding["monthly_cost"]
        saving = round(monthly_cost * SPOT_SAVING_PCT / 100, 2)
        confidence = finding.get("confidence", 0.80)
        instance_type = instance.get("instance_type", "unknown")
        pricing = instance.get("pricing_model", "OnDemand")
        name = instance.get("resource_name", "")

        rationale = (
            f"{name} is {pricing} {instance_type} costing ${monthly_cost:.2f}/month. "
            f"Eligible for Spot pricing with estimated {SPOT_SAVING_PCT:.0f}% saving."
        )

        if finding.get("flag_review"):
            rationale += " Name suggests possible importance — flagged for review."

        return {
            "track": "spot",
            "action": f"Convert {instance_type} from OnDemand to Spot",
            "current_monthly_cost": round(monthly_cost, 2),
            "estimated_monthly_saving": saving,
            "saving_pct": SPOT_SAVING_PCT,
            "confidence": confidence,
            "rationale": rationale,
            "has_performance_data": instance.get("has_performance_data", False),
            "skill_name": self.NAME,
        }

    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        """Generate Spot conversion scripts."""
        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "unknown")
        instance_type = instance.get("instance_type", "")
        region = instance.get("region", "ap-south-1")

        return {
            "terraform_hcl": f'''# Convert {resource_name} ({resource_id}) to Spot
resource "aws_spot_instance_request" "{resource_name.replace("-", "_").replace(" ", "_")}" {{
  ami                    = data.aws_instance.current.ami
  instance_type          = "{instance_type}"
  spot_price             = "auto"
  wait_for_fulfillment   = true
  spot_type              = "persistent"
  instance_interruption_behavior = "stop"

  tags = {{
    Name        = "{resource_name}"
    ManagedBy   = "cloud-sentry-ai"
    PreviousId  = "{resource_id}"
  }}
}}''',
            "aws_cli_command": (
                f"aws ec2 request-spot-instances "
                f"--instance-count 1 "
                f"--type persistent "
                f"--launch-specification '{{\"ImageId\":\"CURRENT_AMI\","
                f"\"InstanceType\":\"{instance_type}\","
                f"\"SubnetId\":\"CURRENT_SUBNET\"}}' "
                f"--region {region}"
            ),
            "rollback_command": (
                f"# Cancel Spot request and launch OnDemand replacement\n"
                f"aws ec2 cancel-spot-instance-requests "
                f"--spot-instance-request-ids SIR_ID --region {region}\n"
                f"aws ec2 run-instances "
                f"--instance-type {instance_type} "
                f"--image-id CURRENT_AMI "
                f"--region {region} "
                f"--tag-specifications 'ResourceType=instance,Tags=[{{Key=Name,Value={resource_name}}}]'"
            ),
            "eventbridge_rule": "",
        }
