"""
skills/remediation/rollback_generator.py
Generates rollback commands for recommendations.
"""
from __future__ import annotations


class RollbackGeneratorSkill:
    NAME = "rollback_generator"
    DISPLAY_NAME = "Rollback Generator"

    def generate(self, instance: dict, recommendation: dict) -> str:
        """Generate rollback command for a recommendation."""
        resource_id = instance.get("resource_id", "")
        region = instance.get("region", "ap-south-1")
        track = recommendation.get("track", "")
        current_type = instance.get("instance_type", "")

        if track == "rightsizing":
            return (
                f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                f"--instance-type {current_type} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            )
        elif track == "spot":
            return (
                f"aws ec2 cancel-spot-instance-requests --spot-instance-request-ids SIR_ID "
                f"--region {region} && "
                f"aws ec2 run-instances --instance-type {current_type} "
                f"--image-id CURRENT_AMI --region {region}"
            )
        elif track == "schedule":
            return (
                f"aws events delete-rule --name cloud-sentry-start-{resource_id} --region {region} && "
                f"aws events delete-rule --name cloud-sentry-stop-{resource_id} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            )
        elif track == "eks":
            return "helm uninstall cluster-autoscaler --namespace kube-system"
        return f"# Manual rollback required for {resource_id}"
