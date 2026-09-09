"""
agents/devops_remediation_agent.py
------------------------------------
DevOps Remediation Agent — generates executable scripts for approved recommendations.

This IS an AI Agent (uses Gemini to generate scripts).

Rules:
  - Only fires when engineer clicks Execute
  - Uses resource_id, resource_name, instance_type, region from recommendation
  - Calls Gemini ONCE per click to generate all 3 scripts
  - Returns: terraform_hcl, aws_cli_command, rollback_command, notes
  - Stores all scripts in remediations table before any execution
  - NEVER use invented resource IDs — always use exact resource_id from recommendation
  - NEVER execute without engineer clicking Confirm and Deploy
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Optional

from core.state_store import StateStore
from core.llm_client import call_gemini


class DevOpsRemediationAgent:
    """
    Generates Terraform, AWS CLI, and rollback scripts for approved recommendations.

    Usage:
        agent = DevOpsRemediationAgent()
        scripts = agent.generate(recommendation)
    """

    def __init__(self):
        self.store = StateStore()

    def generate(self, recommendation: Dict) -> Dict:
        """
        Generate remediation scripts for a single recommendation.

        Args:
            recommendation: Dict from the recommendations table

        Returns:
            {
                "terraform_hcl": str,
                "aws_cli_command": str,
                "rollback_command": str,
                "eventbridge_rule": str,
                "notes": str,
            }
        """
        resource_id = recommendation.get("resource_id", "")
        resource_name = recommendation.get("resource_name", "")
        instance_type = recommendation.get("instance_type", "")
        region = recommendation.get("region", "ap-south-1")
        track = recommendation.get("track", "")
        action = recommendation.get("action", "")
        saving = recommendation.get("estimated_monthly_saving", 0)

        # Call Gemini to generate all scripts in one call
        prompt = f"""You are a senior DevOps engineer generating infrastructure scripts.
Generate Terraform HCL, AWS CLI command, and rollback command for this action.

INSTANCE:
- Resource ID: {resource_id}
- Name: {resource_name}
- Type: {instance_type}
- Region: {region}

ACTION:
- Track: {track}
- Action: {action}
- Estimated saving: ${saving:.2f}/month

RULES:
1. Use the EXACT resource_id "{resource_id}" in all scripts — never invent IDs
2. Include complete, copy-paste-ready commands
3. Always include a rollback command
4. For rightsizing: stop → modify → start
5. For Spot: create spot request, keep AMI/subnet from original
6. For schedule: create EventBridge start/stop rules

Respond with ONLY a JSON object (no markdown):
{{
  "terraform_hcl": "complete Terraform code",
  "aws_cli_command": "complete AWS CLI command with {resource_id}",
  "rollback_command": "complete rollback command with {resource_id}",
  "eventbridge_rule": "EventBridge JSON if schedule track, else empty string",
  "notes": "brief execution notes"
}}"""

        try:
            response = call_gemini(
                prompt=prompt,
                expect_json=True,
                agent="devops_remediation",
                resource_id=resource_id,
            )

            scripts = json.loads(response)

            # Ensure resource_id is in the aws_cli_command
            if resource_id and resource_id not in scripts.get("aws_cli_command", ""):
                scripts["aws_cli_command"] = (
                    f"# Action: {action}\n"
                    f"aws ec2 describe-instances --instance-ids {resource_id} --region {region}"
                )

            # Ensure resource_id is in rollback
            if resource_id and resource_id not in scripts.get("rollback_command", ""):
                scripts["rollback_command"] = (
                    f"# Rollback: restore {resource_name}\n"
                    f"aws ec2 describe-instances --instance-ids {resource_id} --region {region}"
                )

        except Exception as e:
            print(f"[DEVOPS] Gemini script generation failed: {e}")
            # Generate basic scripts without Gemini
            scripts = self._fallback_scripts(recommendation)

        # Ensure all keys exist
        result = {
            "terraform_hcl": scripts.get("terraform_hcl", f"# {action} for {resource_id}"),
            "aws_cli_command": scripts.get("aws_cli_command", f"# {action}\naws ec2 describe-instances --instance-ids {resource_id} --region {region}"),
            "rollback_command": scripts.get("rollback_command", f"# Rollback {resource_name}\naws ec2 describe-instances --instance-ids {resource_id} --region {region}"),
            "eventbridge_rule": scripts.get("eventbridge_rule", ""),
            "notes": scripts.get("notes", f"Generated for {resource_name}"),
        }

        # Save to remediations table
        self.store.save_remediation({
            "recommendation_id": recommendation.get("id", ""),
            "resource_id": resource_id,
            "resource_name": resource_name,
            "action_taken": action,
            "terraform_hcl": result["terraform_hcl"],
            "aws_cli_command": result["aws_cli_command"],
            "rollback_command": result["rollback_command"],
            "eventbridge_rule": result["eventbridge_rule"],
            "status": "GENERATED",
        })

        return result

    def _fallback_scripts(self, recommendation: Dict) -> Dict:
        """Generate basic scripts without Gemini (fallback)."""
        resource_id = recommendation.get("resource_id", "")
        resource_name = recommendation.get("resource_name", "")
        instance_type = recommendation.get("instance_type", "")
        region = recommendation.get("region", "ap-south-1")
        track = recommendation.get("track", "")
        action = recommendation.get("action", "")

        if track == "rightsizing" and "to" in action.lower():
            # Extract target type from action like "Downsize c5.2xlarge to c5.xlarge"
            parts = action.split(" to ")
            target = parts[-1].strip() if len(parts) > 1 else "t3.medium"
            return {
                "terraform_hcl": f'resource "aws_instance" "{resource_name}" {{\n  instance_type = "{target}"\n}}',
                "aws_cli_command": (
                    f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                    f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                    f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                    f"--instance-type {target} --region {region} && "
                    f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
                ),
                "rollback_command": (
                    f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                    f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                    f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                    f"--instance-type {instance_type} --region {region} && "
                    f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
                ),
                "eventbridge_rule": "",
                "notes": f"Fallback script: {action}",
            }
        elif track == "spot":
            return {
                "terraform_hcl": f'resource "aws_spot_instance_request" "{resource_name}" {{\n  instance_type = "{instance_type}"\n  spot_type = "persistent"\n}}',
                "aws_cli_command": f"aws ec2 request-spot-instances --instance-count 1 --type persistent --launch-specification '{{\"InstanceType\":\"{instance_type}\"}}' --region {region}",
                "rollback_command": f"aws ec2 cancel-spot-instance-requests --spot-instance-request-ids SIR_ID --region {region}",
                "eventbridge_rule": "",
                "notes": f"Fallback: Spot conversion for {resource_id}",
            }
        else:
            return {
                "terraform_hcl": f"# {action} for {resource_id}",
                "aws_cli_command": f"aws ec2 describe-instances --instance-ids {resource_id} --region {region}",
                "rollback_command": f"aws ec2 describe-instances --instance-ids {resource_id} --region {region}",
                "eventbridge_rule": "",
                "notes": f"Fallback: {action}",
            }
