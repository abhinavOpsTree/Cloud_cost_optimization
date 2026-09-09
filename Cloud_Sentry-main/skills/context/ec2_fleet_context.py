"""
skills/context/ec2_fleet_context.py
Loads fleet summary as system prompt context for the chat agent.
"""
from __future__ import annotations

import os
import pandas as pd

from core.base_skill import BaseContextSkill


class EC2FleetContextSkill(BaseContextSkill):
    NAME = "ec2_fleet_context"
    DISPLAY_NAME = "EC2 Fleet Context"

    def load_context(self, instances: list = None) -> str:
        cache_path = "cache/enriched_instances.parquet"
        if not os.path.exists(cache_path):
            return "No fleet data available."

        df = pd.read_parquet(cache_path)
        total = len(df)
        total_cost_90d = df["total_cost_90d"].sum()
        monthly_cost = df["monthly_cost_est"].sum()

        # Top 10 by monthly cost
        top10 = df.nlargest(10, "monthly_cost_est")
        top10_lines = []
        for _, row in top10.iterrows():
            name = row.get("resource_name", "unnamed")
            itype = row.get("instance_type", "?")
            mc = row.get("monthly_cost_est", 0)
            c90 = row.get("total_cost_90d", 0)
            env = row.get("inferred_env", "unknown")
            safety = row.get("safety_tier", "APPROVE")
            top10_lines.append(
                f"  - {name}: {itype}, ${mc:.2f}/mo (${c90:.2f}/90d), "
                f"env={env}, safety={safety}"
            )

        # Regional breakdown
        by_region = df.groupby("region").agg(
            count=("resource_id", "count"),
            cost=("monthly_cost_est", "sum"),
        ).sort_values("cost", ascending=False)

        region_lines = []
        for region, row in by_region.iterrows():
            region_lines.append(f"  - {region}: {row['count']} instances, ${row['cost']:.2f}/mo")

        # Pricing breakdown
        by_pricing = df.groupby("pricing_model").agg(
            count=("resource_id", "count"),
            cost=("monthly_cost_est", "sum"),
        )
        pricing_lines = []
        for pm, row in by_pricing.iterrows():
            pricing_lines.append(f"  - {pm}: {row['count']} instances, ${row['cost']:.2f}/mo")

        # Key stats
        eks_count = len(df[df["inferred_workload"] == "EKS_NODE"])
        spot_eligible = len(df[df["is_spot_eligible"] == True])
        hard_blocked = len(df[df["safety_tier"] == "HARD_BLOCK"])
        has_data = len(df[df["has_performance_data"] == True])

        return f"""EC2 FLEET OVERVIEW (AWS Account: {os.getenv("AWS_ACCOUNT_ID", "your-account")})
Pilot period: 18 Feb 2026 to 19 May 2026 (89 days)

Total EC2 instances: {total}
Total EC2 cost (90 days): ${total_cost_90d:.2f}
Monthly run rate: ${monthly_cost:.2f}

Key segments:
  - EKS nodes: {eks_count}
  - Spot-eligible (OnDemand, non-EKS, non-blocked): {spot_eligible}
  - Hard-blocked (production/protected): {hard_blocked}
  - With CloudWatch CPU data: {has_data}
  - Without CPU data: {total - has_data}

Top 10 instances by monthly cost:
{chr(10).join(top10_lines)}

By region:
{chr(10).join(region_lines)}

By pricing model:
{chr(10).join(pricing_lines)}"""
