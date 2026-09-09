"""
skills/governance/risk_flagging.py
-----------------------------------
Tier 2 — Risk Flagging

Runs AFTER Tier 1 (Production Shield). If Tier 1 already blocked the instance,
Tier 2 is never evaluated.

Pure Python — zero Gemini calls.

Conditions that trigger FLAGGED:
  1. EKS node (inferred_workload == "EKS_NODE")
     → Must manage at cluster level, not individually
  2. High inbound network traffic (> 20 Mbps)
     → Possible gateway or data-intensive workload
  3. High outbound network traffic (> 20 Mbps)
  4. Name contains "vpn" → network gateway
  5. Name contains "proxy" → network gateway
  6. CPU spike > 80% → may not be truly idle
  7. Pre-flagged by Fleet Intelligence Processor (safety_tier == "FLAG")

SAFETY RULES:
  RULE 4:  NEVER rightsize EKS node individually — cluster autoscaler only
  RULE 14: FLAGGED instances: checkbox confirmation required before Execute appears

Note on VPN server (17.75 Mbps):
  - 17.75 < 20 Mbps → does NOT trigger Condition 2
  - BUT it IS blocked by Tier 1 ("do no delete" in name) before Tier 2 runs
  - Condition 4 ("vpn" in name) would also catch it as a SECONDARY safety net,
    but Tier 1 always runs first.
"""
from __future__ import annotations

from typing import Optional

from core.base_skill import BaseGovernanceSkill


class RiskFlaggingSkill(BaseGovernanceSkill):
    """
    Tier 2 Risk Flagging — flags instances that need human review.

    FLAGGED is not a permanent block. An engineer can review and approve.
    But the UI requires checkbox confirmation before Execute appears.
    """

    NAME = "risk_flagging"
    DISPLAY_NAME = "Risk Flagging"
    TIER = 2
    DESCRIPTION = "Flags EKS nodes, high-traffic instances, and network gateways"

    # Thresholds (from config.yaml)
    NET_THRESHOLD_MBPS = 20.0
    CPU_SPIKE_THRESHOLD_PCT = 80.0

    def evaluate(self, instance: dict, recommendation: dict) -> Optional[dict]:
        """
        Check if this instance should be flagged for human review.

        Returns a FLAGGED decision dict, or None to pass to Tier 3.

        Conditions are checked in priority order:
          1. EKS node (most common flag in pilot data — 61 instances)
          2. High network traffic
          3. VPN/proxy name pattern
          4. CPU spike
          5. Pre-flagged by FIP
        """
        name = str(instance.get("resource_name", "")).lower()
        workload = str(instance.get("inferred_workload", ""))

        # Get numeric values safely (None if not available)
        net_in = instance.get("net_in_mbps")
        net_out = instance.get("net_out_mbps")
        cpu_max = instance.get("cpu_max_pct")
        safety_from_fip = str(instance.get("safety_tier", ""))

        # ---------------------------------------------------------------
        # Condition 1 — "do not delete" for non-termination actions
        # ---------------------------------------------------------------
        if "do no delete" in name or "do not delete" in name:
            track = str(recommendation.get("track", "")).lower()
            if track not in ("termination", "deletion"):
                return {
                    "status": "FLAGGED",
                    "tier": 2,
                    "reason": "Instance is marked 'do not delete' — action is not deletion, but requires explicit human approval",
                }

        # ---------------------------------------------------------------
        # Condition 2 — EKS node (cluster-level management only)
        # Catches all 61 EKS nodes in pilot data
        # ---------------------------------------------------------------
        if workload == "EKS_NODE":
            cluster = instance.get("cluster_name", "unknown cluster")
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": f"EKS node (cluster: {cluster}) — manage at cluster level only, not individually",
            }

        # ---------------------------------------------------------------
        # Condition 2 — High inbound traffic (> 20 Mbps)
        # Note: VPN server is 17.75 Mbps which is BELOW this threshold
        # ---------------------------------------------------------------
        if net_in is not None and net_in > self.NET_THRESHOLD_MBPS:
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": f"High inbound traffic {net_in:.1f} Mbps — possible gateway or data-intensive workload",
            }

        # ---------------------------------------------------------------
        # Condition 3 — High outbound traffic (> 20 Mbps)
        # ---------------------------------------------------------------
        if net_out is not None and net_out > self.NET_THRESHOLD_MBPS:
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": f"High outbound traffic {net_out:.1f} Mbps — possible data export workload",
            }

        # ---------------------------------------------------------------
        # Condition 4 — Name contains "vpn"
        # Secondary safety net for network gateways
        # ---------------------------------------------------------------
        if "vpn" in name:
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": "Name contains 'vpn' — network gateway, risky to modify",
            }

        # ---------------------------------------------------------------
        # Condition 5 — Name contains "proxy"
        # Secondary safety net for proxy servers
        # ---------------------------------------------------------------
        if "proxy" in name:
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": "Name contains 'proxy' — network gateway, risky to modify",
            }

        # ---------------------------------------------------------------
        # Condition 6 — CPU spike > 80%
        # Instance may not be truly idle despite low average
        # ---------------------------------------------------------------
        if cpu_max is not None and cpu_max > self.CPU_SPIKE_THRESHOLD_PCT:
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": f"CPU spiked to {cpu_max:.1f}% — may not be truly idle, needs review",
            }

        # ---------------------------------------------------------------
        # Condition 7 — Pre-flagged by Fleet Intelligence Processor
        # ---------------------------------------------------------------
        if safety_from_fip == "FLAG":
            return {
                "status": "FLAGGED",
                "tier": 2,
                "reason": "Flagged by Fleet Intelligence Processor at ingest time",
            }

        # Passes Tier 2 — proceed to Tier 3
        return None
