"""
skills/analysis/rightsizing.py
-------------------------------
Rightsizing Skill — recommends downsizing over-provisioned instances.

Only applies to instances with has_performance_data == True (18 instances).
Uses OVER_PROVISIONED and SEVERELY_OVER_PROVISIONED signals from FIP.
Checks net_in_mbps — if > 20 Mbps despite low CPU, FLAG not rightsize.

Pure Python — zero Gemini calls.
"""
from __future__ import annotations

from core.base_skill import BaseAnalysisSkill


# Replace DOWNSIZE_MAP and APPROX_COSTS with this:
_FAMILY_LADDERS = {
    "t2":  ["t2.2xlarge", "t2.xlarge", "t2.large", "t2.medium", "t2.small", "t2.micro"],
    "t3":  ["t3.2xlarge", "t3.xlarge", "t3.large", "t3.medium", "t3.small", "t3.micro"],
    "t3a": ["t3a.2xlarge", "t3a.xlarge", "t3a.large", "t3a.medium", "t3a.small", "t3a.micro"],
    "m5":  ["m5.4xlarge", "m5.2xlarge", "m5.xlarge", "m5.large"],
    "m5a": ["m5a.4xlarge", "m5a.2xlarge", "m5a.xlarge", "m5a.large"],
    "c5":  ["c5.4xlarge", "c5.2xlarge", "c5.xlarge", "c5.large"],
    "c5a": ["c5a.4xlarge", "c5a.2xlarge", "c5a.xlarge", "c5a.large"],
    "r5":  ["r5.4xlarge", "r5.2xlarge", "r5.xlarge", "r5.large"],
}


class RightsizingSkill(BaseAnalysisSkill):
    """Rightsizing recommendations for over-provisioned instances."""

    NAME = "rightsizing"
    DISPLAY_NAME = "Rightsizing"
    DESCRIPTION = "Recommends downsizing for instances with low CPU utilization"
    TRACK = "rightsizing"
    VERSION = "1.0.0"

    def _recommend_target_type(self, current_type: str, cpu_p95: float, has_cpu_data: bool) -> dict:
        """
        CPU-aware instance type recommendation.
        Returns dict with: recommended_type, saving_factor, confidence, confidence_band, reasoning
        """
        family = current_type.split(".")[0] if "." in current_type else ""
        ladder = _FAMILY_LADDERS.get(family, [])

        # No CPU data — conservative one-step down
        if not has_cpu_data:
            if "xlarge" in current_type:
                recommended = "t3.large"
            elif "large" in current_type:
                recommended = "t3.medium"
            elif "medium" in current_type:
                recommended = "t3.small"
            else:
                recommended = current_type
            return {
                "recommended_type": recommended,
                "saving_factor": 0.40 if recommended != current_type else 0.0,
                "confidence": 0.55,
                "confidence_band": "amber",
                "reasoning": "No CloudWatch CPU data — conservative one-step downsize based on instance size only.",
            }

        # CPU p95 > 60% — DO NOT resize, it is actively used
        if cpu_p95 > 60:
            return {
                "recommended_type": current_type,
                "saving_factor": 0.0,
                "confidence": 0.95,
                "confidence_band": "red",
                "reasoning": f"CPU p95 = {cpu_p95:.1f}% — instance is actively used. Downsizing would cause performance degradation.",
            }

        # CPU p95 30–60% — keep size, recommend Spot instead
        if cpu_p95 > 30:
            return {
                "recommended_type": current_type,
                "saving_factor": 0.0,
                "confidence": 0.80,
                "confidence_band": "amber",
                "reasoning": f"CPU p95 = {cpu_p95:.1f}% — sized appropriately for workload. Recommend Spot conversion instead of resize.",
            }

        # CPU p95 10–30% — one step down the family ladder
        if cpu_p95 > 10:
            if ladder and current_type in ladder:
                idx = ladder.index(current_type)
                recommended = ladder[min(idx + 1, len(ladder) - 1)]
            else:
                recommended = current_type
            return {
                "recommended_type": recommended,
                "saving_factor": 0.45,
                "confidence": 0.85,
                "confidence_band": "green",
                "reasoning": f"CPU p95 = {cpu_p95:.1f}% — comfortable headroom for one-step downsize.",
            }

        # CPU p95 < 10% — two steps down (severely over-provisioned)
        if ladder and current_type in ladder:
            idx = ladder.index(current_type)
            recommended = ladder[min(idx + 2, len(ladder) - 1)]
        else:
            recommended = "t3.small"
        return {
            "recommended_type": recommended,
            "saving_factor": 0.65,
            "confidence": 0.92,
            "confidence_band": "green",
            "reasoning": f"CPU p95 = {cpu_p95:.1f}% — severely over-provisioned, aggressive downsize is safe.",
        }

    def can_apply(self, instance: dict) -> bool:
        """Only applies to instances with performance data."""
        if not instance.get("has_performance_data"):
            return False
        # Skip EKS nodes (managed at cluster level)
        if instance.get("inferred_workload") == "EKS_NODE":
            return False
        return True

    def analyse(self, instance: dict) -> dict:
        """Check CPU utilization and network traffic."""
        signal = instance.get("rightsizing_signal", "")
        cpu_avg = instance.get("cpu_avg_pct")
        cpu_p95 = float(instance.get("cpu_p95_pct") or 0.0)
        net_in = instance.get("net_in_mbps") or 0
        has_cpu = instance.get("has_performance_data", False)

        if signal not in ("OVER_PROVISIONED", "SEVERELY_OVER_PROVISIONED"):
            return {}

        if net_in > 20:
            return {"signal": signal, "flag_reason": "high_network", "net_in": net_in}

        return {
            "signal": signal,
            "cpu_avg": cpu_avg,
            "cpu_p95": cpu_p95,
            "has_cpu_data": has_cpu,
            "instance_type": instance.get("instance_type", ""),
        }

    def recommend(self, instance: dict, finding: dict) -> dict | None:
        """Convert finding to recommendation."""
        if not finding or not finding.get("signal"):
            return None
        if finding.get("flag_reason") == "high_network":
            return None

        instance_type = instance.get("instance_type", "")
        cpu_p95 = finding.get("cpu_p95", 0.0)
        has_cpu_data = finding.get("has_cpu_data", False)
        current_cost = instance.get("monthly_cost_est", 0.0) or 0.0

        result = self._recommend_target_type(instance_type, cpu_p95, has_cpu_data)
        target_type = result["recommended_type"]

        # If no downsize possible (same type), return None — no recommendation
        if target_type == instance_type and result["saving_factor"] == 0.0:
            # But still return if reason is "use Spot instead" — that is handled by SpotConversionSkill
            return None

        estimated_saving = round(current_cost * result["saving_factor"], 2)

        return {
            "track": "rightsizing",
            "action": f"Downsize {instance_type} -> {target_type}" if target_type != instance_type else "Convert to Spot pricing (sized appropriately for CPU)",
            "current_monthly_cost": round(current_cost, 2),
            "estimated_monthly_saving": estimated_saving,
            "saving_pct": round(result["saving_factor"] * 100, 1),
            "confidence": result["confidence"],
            "confidence_band": result.get("confidence_band", "amber"),
            "rationale": result["reasoning"],
            "has_performance_data": has_cpu_data,
            "skill_name": self.NAME,
            "target_type": target_type,
        }

    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        """Generate Terraform, AWS CLI, and rollback scripts."""
        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "unknown")
        current_type = instance.get("instance_type", "")
        target_type = recommendation.get("target_type", "")
        region = instance.get("region", "ap-south-1")

        return {
            "terraform_hcl": f'''# Rightsize {resource_name} ({resource_id})
# {current_type} → {target_type}
resource "aws_instance" "{resource_name.replace("-", "_").replace(" ", "_")}" {{
  instance_type = "{target_type}"  # downsized from {current_type}
  # NOTE: Stop instance first, then modify, then start
}}''',
            "aws_cli_command": (
                f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                f"--instance-type {target_type} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            ),
            "rollback_command": (
                f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                f"--instance-type {current_type} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            ),
            "eventbridge_rule": "",
        }
