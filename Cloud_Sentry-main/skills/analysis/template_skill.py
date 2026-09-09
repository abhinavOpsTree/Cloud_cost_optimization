"""
skills/analysis/template_skill.py
----------------------------------
Template for creating new Cloud-Sentry AI analysis skills.

Copy this file, rename it, and implement the 4 methods.
See CONTRIBUTING_A_SKILL.md for the full guide.

Time to create a new skill: 15-30 minutes.

Example implementations:
  - skills/analysis/rightsizing.py      (rightsizing recommendations)
  - skills/analysis/spot_conversion.py  (Spot conversion analysis)
  - skills/analysis/schedule_policy.py  (stop/start scheduling)
  - skills/analysis/eks_diagnosis.py    (EKS cluster optimization)
"""
from core.base_skill import BaseAnalysisSkill


class TemplateSkill(BaseAnalysisSkill):
    """
    [YOUR SKILL NAME] Skill

    Purpose:
        [Describe what this skill analyses and what recommendations it produces]

    Applies to:
        [Describe which instances this skill targets]

    Track: [rightsizing | spot | schedule | eks | tagging | custom]
    """

    # Metadata — used by the skill registry and leaderboard
    NAME = "template_skill"
    DISPLAY_NAME = "Template Skill"
    DESCRIPTION = "A template for building new analysis skills"
    TRACK = "custom"  # Change to: rightsizing, spot, schedule, eks, tagging
    VERSION = "1.0.0"
    AUTHOR = "Your Name"

    def can_apply(self, instance: dict) -> bool:
        """
        Return True if this skill should run for the given instance.

        Args:
            instance: A dict row from enriched_instances.parquet
                Keys available:
                - resource_id, resource_name, instance_type, pricing_model
                - cpu_avg_pct, cpu_max_pct, net_in_mbps, net_out_mbps
                - has_performance_data (bool)
                - inferred_env, inferred_workload, safety_tier
                - is_spot_eligible (bool)
                - total_cost_90d, monthly_cost_est
                - cluster_name (str or None)

        Example:
            # Only apply to instances with performance data
            return instance.get("has_performance_data") == True

            # Only apply to OnDemand instances
            return instance.get("pricing_model") == "OnDemand"
        """
        # TODO: Replace with your logic
        return False

    def analyse(self, instance: dict) -> dict:
        """
        Analyse the instance and return findings.

        Returns:
            A dict with your findings. Return {} if no actionable finding.

        Example:
            cpu_avg = instance.get("cpu_avg_pct", 0)
            if cpu_avg < 10:
                return {
                    "signal": "UNDER_UTILISED",
                    "cpu_avg": cpu_avg,
                    "recommended_action": "Consider downsizing",
                }
            return {}
        """
        # TODO: Replace with your analysis logic
        return {}

    def recommend(self, instance: dict, finding: dict) -> dict | None:
        """
        Convert a finding into a recommendation.

        Args:
            instance: Instance data
            finding:  Dict returned by analyse()

        Returns:
            A recommendation dict or None.

        Required keys in recommendation:
            track:                    str   — "rightsizing"|"spot"|"schedule"|"eks"|"custom"
            action:                   str   — human-readable description
            current_monthly_cost:     float — from instance["monthly_cost_est"]
            estimated_monthly_saving: float — your estimate
            saving_pct:               float — percentage saved
            confidence:               float — 0.0 to 1.0
            rationale:                str   — shown to the engineer
            has_performance_data:     bool  — from instance["has_performance_data"]
            skill_name:               str   — self.NAME

        Example:
            return {
                "track": "rightsizing",
                "action": f"Downsize {instance['instance_type']} to t3.small",
                "current_monthly_cost": instance.get("monthly_cost_est", 0),
                "estimated_monthly_saving": 5.00,
                "saving_pct": 40.0,
                "confidence": 0.85,
                "rationale": f"CPU avg {finding['cpu_avg']:.1f}% — instance over-provisioned",
                "has_performance_data": instance.get("has_performance_data", False),
                "skill_name": self.NAME,
            }
        """
        # TODO: Replace with your recommendation logic
        return None

    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        """
        Generate executable scripts for the recommendation.

        Returns:
            {
                "terraform_hcl":     str — complete Terraform code
                "aws_cli_command":   str — complete AWS CLI command
                "rollback_command":  str — complete rollback command
                "eventbridge_rule":  str — EventBridge JSON (schedule only, else "")
            }

        IMPORTANT:
            - Use real instance IDs, not placeholders
            - Always include a rollback command
            - Scripts must be copy-paste ready

        Example:
            resource_id = instance["resource_id"]
            return {
                "terraform_hcl": f'''
resource "aws_instance" "{instance['resource_name']}" {{
  instance_type = "t3.small"  # downsized from {instance['instance_type']}
}}
''',
                "aws_cli_command": f"aws ec2 modify-instance-attribute --instance-id {resource_id} --instance-type t3.small",
                "rollback_command": f"aws ec2 modify-instance-attribute --instance-id {resource_id} --instance-type {instance['instance_type']}",
                "eventbridge_rule": "",
            }
        """
        # TODO: Replace with your script generation logic
        return {
            "terraform_hcl": "# TODO: Add Terraform code",
            "aws_cli_command": "# TODO: Add AWS CLI command",
            "rollback_command": "# TODO: Add rollback command",
            "eventbridge_rule": "",
        }
