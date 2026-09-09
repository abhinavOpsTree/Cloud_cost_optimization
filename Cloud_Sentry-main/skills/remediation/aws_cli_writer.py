"""
skills/remediation/aws_cli_writer.py
Generates AWS CLI commands for recommendations.
"""
from __future__ import annotations


class AWSCLIWriterSkill:
    NAME = "aws_cli_writer"
    DISPLAY_NAME = "AWS CLI Writer"

    def generate(self, instance: dict, recommendation: dict) -> str:
        """Generate AWS CLI command for a recommendation."""
        resource_id = instance.get("resource_id", "")
        region = instance.get("region", "ap-south-1")
        track = recommendation.get("track", "")

        if track == "rightsizing":
            target = recommendation.get("target_type", "")
            return (
                f"aws ec2 stop-instances --instance-ids {resource_id} --region {region} && "
                f"aws ec2 wait instance-stopped --instance-ids {resource_id} --region {region} && "
                f"aws ec2 modify-instance-attribute --instance-id {resource_id} "
                f"--instance-type {target} --region {region} && "
                f"aws ec2 start-instances --instance-ids {resource_id} --region {region}"
            )
        elif track == "spot":
            return (
                f"aws ec2 request-spot-instances --instance-count 1 --type persistent "
                f"--launch-specification '{{\"InstanceType\":\"{instance.get('instance_type','')}\","
                f"\"ImageId\":\"CURRENT_AMI\"}}' --region {region}"
            )
        elif track == "schedule":
            return (
                f"aws events put-rule --name cloud-sentry-start-{resource_id} "
                f"--schedule-expression 'cron({recommendation.get('cron_start','')})' "
                f"--region {region}"
            )
        elif track == "eks":
            cluster = recommendation.get("cluster_name", "unknown")
            return (
                f"helm install cluster-autoscaler autoscaler/cluster-autoscaler "
                f"--namespace kube-system --set autoDiscovery.clusterName={cluster}"
            )
        return f"# Manual action required for {resource_id}"
