"""
skills/remediation/terraform_writer.py
Generates Terraform HCL for recommendations.
"""
from __future__ import annotations


class TerraformWriterSkill:
    NAME = "terraform_writer"
    DISPLAY_NAME = "Terraform Writer"

    def generate(self, instance: dict, recommendation: dict) -> str:
        """Generate Terraform HCL for a recommendation."""
        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "unknown")
        track = recommendation.get("track", "")
        action = recommendation.get("action", "")
        safe_name = resource_name.replace("-", "_").replace(" ", "_")

        if track == "rightsizing":
            target_type = recommendation.get("target_type", "")
            current_type = instance.get("instance_type", "")
            return f'''# Rightsize {resource_name} ({resource_id})
resource "aws_instance" "{safe_name}" {{
  instance_type = "{target_type}"  # downsized from {current_type}
}}'''
        elif track == "spot":
            return f'''# Spot conversion {resource_name} ({resource_id})
resource "aws_spot_instance_request" "{safe_name}" {{
  ami           = data.aws_instance.current.ami
  instance_type = "{instance.get("instance_type", "")}"
  spot_type     = "persistent"
}}'''
        elif track == "schedule":
            return f'''# Schedule {resource_name} ({resource_id})
# Action: {action}
# Use EventBridge rules for stop/start scheduling'''
        elif track == "eks":
            cluster = recommendation.get("cluster_name", "unknown")
            return f'''# EKS Autoscaler for {cluster}
resource "helm_release" "autoscaler_{cluster.replace("-","_")}" {{
  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"
  namespace  = "kube-system"
  set {{
    name  = "autoDiscovery.clusterName"
    value = "{cluster}"
  }}
}}'''
        return f"# {action} for {resource_id}"
