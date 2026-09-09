"""
skills/remediation/eventbridge_writer.py
Generates EventBridge rules for schedule-based recommendations.
"""
from __future__ import annotations
import json


class EventBridgeWriterSkill:
    NAME = "eventbridge_writer"
    DISPLAY_NAME = "EventBridge Writer"

    def generate(self, instance: dict, recommendation: dict) -> str:
        """Generate EventBridge rule JSON for schedule recommendations."""
        if recommendation.get("track") != "schedule":
            return ""

        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "unknown")
        region = instance.get("region", "ap-south-1")
        cron_start = recommendation.get("cron_start", "0 9 ? * MON-FRI *")
        cron_stop = recommendation.get("cron_stop", "0 21 ? * MON-FRI *")
        tier = recommendation.get("schedule_tier", "CRITICAL_WASTE")

        rules = {
            "start_rule": {
                "Name": f"cloud-sentry-start-{resource_id}",
                "ScheduleExpression": f"cron({cron_start})",
                "State": "ENABLED",
                "Description": f"Start {resource_name} - {tier} schedule",
            },
            "stop_rule": {
                "Name": f"cloud-sentry-stop-{resource_id}",
                "ScheduleExpression": f"cron({cron_stop})",
                "State": "ENABLED",
                "Description": f"Stop {resource_name} - {tier} schedule",
            },
        }
        return json.dumps(rules, indent=2)
