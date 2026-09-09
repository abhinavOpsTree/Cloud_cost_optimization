"""
skills/analysis/schedule_policy.py
------------------------------------
Schedule Policy Skill — recommends stop/start scheduling for underutilized instances.

Only applies to instances with has_performance_data == True.
Uses cpu_avg_pct to assign schedule tier:
  <10% → CRITICAL_WASTE → 09:00-21:00 IST weekdays + weekend off → ~50% saving
  10-20% → LOW_WASTE → 18h window → ~25% saving
  20-30% → MEDIUM_WASTE → 16h window → ~33% saving
  >30% → OPTIMISED → no action

Never applies to: HARD_BLOCK, EKS_NODE, NETWORK_GATEWAY

Pure Python — zero Gemini calls.
"""
from __future__ import annotations

from core.base_skill import BaseAnalysisSkill

TIMEZONE = "Asia/Kolkata"

SCHEDULE_TIERS = {
    "CRITICAL_WASTE": {
        "cpu_max": 10.0,
        "window": "09:00-21:00",
        "saving_pct": 50.0,
        "cron_start": "0 9 ? * MON-FRI *",
        "cron_stop": "0 21 ? * MON-FRI *",
        "description": "Run 09:00-21:00 IST weekdays only, off weekends",
    },
    "LOW_WASTE": {
        "cpu_min": 10.0,
        "cpu_max": 20.0,
        "window": "06:00-00:00",
        "saving_pct": 25.0,
        "cron_start": "0 6 ? * * *",
        "cron_stop": "0 0 ? * * *",
        "description": "Run 06:00-00:00 IST daily (18h window)",
    },
    "MEDIUM_WASTE": {
        "cpu_min": 20.0,
        "cpu_max": 30.0,
        "window": "08:00-00:00",
        "saving_pct": 33.0,
        "cron_start": "0 8 ? * * *",
        "cron_stop": "0 0 ? * * *",
        "description": "Run 08:00-00:00 IST daily (16h window)",
    },
}


class SchedulePolicySkill(BaseAnalysisSkill):
    """Schedule-based cost savings for underutilized instances."""

    NAME = "schedule_policy"
    DISPLAY_NAME = "Schedule Policy"
    DESCRIPTION = "Recommends stop/start scheduling to reduce waste"
    TRACK = "schedule"
    VERSION = "1.0.0"

    def can_apply(self, instance: dict) -> bool:
        if not instance.get("has_performance_data"):
            return False
        if instance.get("safety_tier") == "HARD_BLOCK":
            return False
        if instance.get("inferred_workload") in ("EKS_NODE", "NETWORK_GATEWAY"):
            return False
        return True

    def analyse(self, instance: dict) -> dict:
        cpu_avg = instance.get("cpu_avg_pct")
        if cpu_avg is None:
            return {}

        if cpu_avg < 10:
            return {"tier": "CRITICAL_WASTE", "cpu_avg": cpu_avg}
        elif cpu_avg < 20:
            return {"tier": "LOW_WASTE", "cpu_avg": cpu_avg}
        elif cpu_avg < 30:
            return {"tier": "MEDIUM_WASTE", "cpu_avg": cpu_avg}
        else:
            return {}  # OPTIMISED — no action

    def recommend(self, instance: dict, finding: dict) -> dict | None:
        if not finding or not finding.get("tier"):
            return None

        tier_name = finding["tier"]
        tier = SCHEDULE_TIERS.get(tier_name)
        if not tier:
            return None

        monthly_cost = instance.get("monthly_cost_est", 0.0) or 0.0
        saving_pct = tier["saving_pct"]
        saving = round(monthly_cost * saving_pct / 100, 2)
        cpu_avg = finding.get("cpu_avg", 0)
        window = tier["window"]

        return {
            "track": "schedule",
            "action": f"Apply {tier_name} schedule: {tier['description']}",
            "current_monthly_cost": round(monthly_cost, 2),
            "estimated_monthly_saving": saving,
            "saving_pct": saving_pct,
            "confidence": 0.85,
            "rationale": (
                f"CPU avg {cpu_avg:.1f}% ({tier_name}). "
                f"Schedule {window} IST saves ~{saving_pct:.0f}%."
            ),
            "has_performance_data": True,
            "skill_name": self.NAME,
            "schedule_tier": tier_name,
            "schedule_window": window,
            "cron_start": tier["cron_start"],
            "cron_stop": tier["cron_stop"],
        }

    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "unknown")
        region = instance.get("region", "ap-south-1")
        cron_start = recommendation.get("cron_start", "0 9 ? * MON-FRI *")
        cron_stop = recommendation.get("cron_stop", "0 21 ? * MON-FRI *")
        tier_name = recommendation.get("schedule_tier", "CRITICAL_WASTE")
        window = recommendation.get("schedule_window", "09:00-21:00")

        import json as _json
        eb_start = _json.dumps({
            "Name": f"cloud-sentry-start-{resource_id}",
            "ScheduleExpression": f"cron({cron_start})",
            "State": "ENABLED",
            "Description": f"Start {resource_name} - {tier_name} schedule",
            "Targets": [{
                "Id": f"start-{resource_id}",
                "Arn": f"arn:aws:ssm:{region}::automation-definition/AWS-StartEC2Instance",
                "Input": _json.dumps({"InstanceId": [resource_id]}),
            }],
        }, indent=2)

        eb_stop = _json.dumps({
            "Name": f"cloud-sentry-stop-{resource_id}",
            "ScheduleExpression": f"cron({cron_stop})",
            "State": "ENABLED",
            "Description": f"Stop {resource_name} - {tier_name} schedule",
            "Targets": [{
                "Id": f"stop-{resource_id}",
                "Arn": f"arn:aws:ssm:{region}::automation-definition/AWS-StopEC2Instance",
                "Input": _json.dumps({"InstanceId": [resource_id]}),
            }],
        }, indent=2)

        return {
            "terraform_hcl": f'''# Schedule {resource_name} ({resource_id})
# {tier_name}: {window} IST
resource "aws_cloudwatch_event_rule" "start_{resource_id.replace("-","_")}" {{
  name                = "cloud-sentry-start-{resource_id}"
  schedule_expression = "cron({cron_start})"
  description         = "Start {resource_name} - {tier_name}"
}}

resource "aws_cloudwatch_event_rule" "stop_{resource_id.replace("-","_")}" {{
  name                = "cloud-sentry-stop-{resource_id}"
  schedule_expression = "cron({cron_stop})"
  description         = "Stop {resource_name} - {tier_name}"
}}''',
            "aws_cli_command": (
                f"aws events put-rule --name cloud-sentry-start-{resource_id} "
                f"--schedule-expression 'cron({cron_start})' --region {region} && "
                f"aws events put-rule --name cloud-sentry-stop-{resource_id} "
                f"--schedule-expression 'cron({cron_stop})' --region {region}"
            ),
            "rollback_command": (
                f"aws events delete-rule --name cloud-sentry-start-{resource_id} --region {region} && "
                f"aws events delete-rule --name cloud-sentry-stop-{resource_id} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            ),
            "eventbridge_rule": f"{eb_start}\n---\n{eb_stop}",
        }
