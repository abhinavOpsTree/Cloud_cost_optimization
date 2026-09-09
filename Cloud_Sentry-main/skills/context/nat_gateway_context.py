"""
skills/context/nat_gateway_context.py
Loads NAT Gateway breakdown as context for the chat agent.
"""
from __future__ import annotations

import os
import pandas as pd

from core.base_skill import BaseContextSkill


class NATGatewayContextSkill(BaseContextSkill):
    NAME = "nat_gateway_context"
    DISPLAY_NAME = "NAT Gateway Context"

    def load_context(self, instances: list = None) -> str:
        cache_path = "cache/nat_gateway_data.parquet"
        if not os.path.exists(cache_path):
            return "No NAT Gateway data available."

        df = pd.read_parquet(cache_path)
        total_cost_90d = df["cost_90d"].sum()
        monthly_cost = total_cost_90d / 89 * 30

        lines = [
            f"NAT GATEWAY COST BREAKDOWN",
            f"Total NAT Gateway cost (90 days): ${total_cost_90d:.2f}",
            f"Monthly run rate: ${monthly_cost:.2f}",
            f"Number of NAT Gateways: {len(df)}",
            f"",
            f"Per-gateway breakdown:"
        ]

        for _, row in df.sort_values("cost_90d", ascending=False).iterrows():
            name = row.get("resource_name", "unnamed")
            rid = row.get("resource_id", "")
            region = row.get("region", "")
            cost = row.get("cost_90d", 0)
            mc = cost / 89 * 30
            lines.append(f"  - {name or rid}: ${mc:.2f}/mo (${cost:.2f}/90d) [{region}]")

        lines.append("")
        lines.append("KEY INSIGHT: NAT Gateway costs are driven by EKS clusters pulling container images.")
        lines.append("Recommended: Use VPC endpoints for ECR/S3 to reduce NAT traversal.")

        return "\n".join(lines)
