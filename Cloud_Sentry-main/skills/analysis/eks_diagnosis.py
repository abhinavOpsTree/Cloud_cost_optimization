"""
skills/analysis/eks_diagnosis.py
----------------------------------
EKS Diagnosis Skill — cluster-level optimization for EKS nodes.

Groups EKS nodes by cluster_name.
Generates ONE recommendation per cluster (not per node).
Recommendation: "Enable Cluster Autoscaler"
Never recommends rightsizing or Spot for individual EKS nodes.

Pure Python — zero Gemini calls.
"""
from __future__ import annotations

from core.base_skill import BaseAnalysisSkill


class EKSDiagnosisSkill(BaseAnalysisSkill):
    """
    EKS cluster-level optimization.

    This skill is unique: it tracks which clusters have been processed
    and generates ONE recommendation per cluster, not per node.
    """

    NAME = "eks_diagnosis"
    DISPLAY_NAME = "EKS Diagnosis"
    DESCRIPTION = "Recommends cluster autoscaler for EKS clusters"
    TRACK = "eks"
    VERSION = "1.0.0"

    def __init__(self):
        super().__init__()
        self._processed_clusters: set = set()

    def reset(self):
        """Reset cluster tracking between runs."""
        self._processed_clusters = set()

    def _normalize_cluster(self, raw_name: str) -> str:
        """
        Normalize cluster name to avoid counting node groups as separate clusters.

        e.g. 'ot-mumbai-v1-34-standard-nodes' → 'ot-mumbai-v1-34'
             'ot-mumbai-v1-34'                → 'ot-mumbai-v1-34'
        """
        if not raw_name:
            return "unknown-cluster"
        name = raw_name.strip()
        # Strip node-group suffixes — same EKS cluster
        for suffix in ["-standard-nodes", "-nodes"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        return name or "unknown-cluster"

    def can_apply(self, instance: dict) -> bool:
        if instance.get("inferred_workload") != "EKS_NODE":
            return False
        raw_cluster = instance.get("cluster_name") or "unknown-cluster"
        cluster = self._normalize_cluster(raw_cluster)
        # Only process each cluster once
        if cluster in self._processed_clusters:
            return False
        return True

    def analyse(self, instance: dict) -> dict:
        """Gather cluster info from the first node encountered."""
        raw_cluster = instance.get("cluster_name") or "unknown-cluster"
        cluster = self._normalize_cluster(raw_cluster)
        self._processed_clusters.add(cluster)

        return {
            "cluster_name": cluster,
            "first_node_type": instance.get("instance_type", ""),
            "first_node_region": instance.get("region", ""),
        }

    def recommend(self, instance: dict, finding: dict) -> dict | None:
        if not finding or not finding.get("cluster_name"):
            return None

        cluster = finding["cluster_name"]
        node_type = finding.get("first_node_type", "unknown")
        region = finding.get("first_node_region", "ap-south-1")

        return {
            "track": "eks",
            "action": f"Enable Cluster Autoscaler for {cluster}",
            "current_monthly_cost": 0.0,  # cluster-level, not instance-level
            "estimated_monthly_saving": 0.0,  # requires cluster-level analysis
            "saving_pct": 0.0,
            "confidence": 0.75,
            "rationale": (
                f"EKS cluster '{cluster}' has nodes running as {node_type}. "
                f"Enable Cluster Autoscaler to right-size the node group automatically. "
                f"Do NOT rightsize or Spot-convert individual EKS nodes."
            ),
            "has_performance_data": False,
            "skill_name": self.NAME,
            "cluster_name": cluster,
            "node_type": node_type,
            "region": region,
        }

    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        cluster = recommendation.get("cluster_name", "unknown")
        region = recommendation.get("region", "ap-south-1")

        return {
            "terraform_hcl": f'''# Enable Cluster Autoscaler for {cluster}
resource "helm_release" "cluster_autoscaler_{cluster.replace("-","_")}" {{
  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"
  namespace  = "kube-system"

  set {{
    name  = "autoDiscovery.clusterName"
    value = "{cluster}"
  }}

  set {{
    name  = "awsRegion"
    value = "{region}"
  }}

  set {{
    name  = "extraArgs.balance-similar-node-groups"
    value = "true"
  }}

  set {{
    name  = "extraArgs.skip-nodes-with-system-pods"
    value = "true"
  }}
}}''',
            "aws_cli_command": (
                f"# Install Cluster Autoscaler via Helm\n"
                f"helm repo add autoscaler https://kubernetes.github.io/autoscaler\n"
                f"helm install cluster-autoscaler autoscaler/cluster-autoscaler "
                f"--namespace kube-system "
                f"--set autoDiscovery.clusterName={cluster} "
                f"--set awsRegion={region}"
            ),
            "rollback_command": (
                f"helm uninstall cluster-autoscaler --namespace kube-system"
            ),
            "eventbridge_rule": "",
        }
