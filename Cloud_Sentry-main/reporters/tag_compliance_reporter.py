"""
reporters/tag_compliance_reporter.py
-------------------------------------
Tag Compliance Reporter — generates tag health metrics for the OpsTree fleet.

NOT an Agent (no Gemini calls). This is a pure-Python Reporter.

Reads: cache/enriched_instances.parquet
Produces:
  - Tag health score and coverage metrics
  - Per-field coverage percentages
  - Untagged instance list sorted by cost
  - CSV export on demand

Key metrics from pilot data:
  env/environment tag coverage: ~15.1% (42 of 279)
  owner tag coverage: ~1.8% (5 of 279)
  team tag coverage: ~0.7% (2 of 279)
  app tag coverage: 0% (0 of 279)
  Unattributed spend (no env tag): ~$300 over 89 days
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


class TagComplianceReporter:
    """
    Analyses tag coverage across the fleet and produces compliance reports.

    Usage:
        reporter = TagComplianceReporter()
        report = reporter.generate_report()
    """

    # Fields to audit
    AUDIT_FIELDS = ["env", "environment", "Environment", "owner", "team", "app"]

    # Canonical field grouping (different tag keys → same concept)
    FIELD_GROUPS = {
        "env": ["env", "environment", "Environment"],
        "owner": ["owner", "Owner"],
        "team": ["team", "Team"],
        "app": ["app", "application", "Application"],
    }

    def __init__(self, cache_path: str = "cache/enriched_instances.parquet"):
        self.cache_path = cache_path

    def generate_report(self) -> dict:
        """
        Generate the full tag compliance report.

        Returns:
            {
                "total_instances": int,
                "health_score_pct": float,
                "field_coverage": {field: {count, pct, missing}},
                "untagged_instances": [{name, type, region, monthly_cost, missing_tags, suggested_env, confidence}],
                "unattributed_spend_90d": float,
                "unattributed_spend_monthly": float,
                "generated_at": str,
            }
        """
        if not os.path.exists(self.cache_path):
            return {
                "total_instances": 0,
                "health_score_pct": 0.0,
                "field_coverage": {},
                "untagged_instances": [],
                "unattributed_spend_90d": 0.0,
                "unattributed_spend_monthly": 0.0,
                "generated_at": datetime.utcnow().isoformat(),
                "error": "No enriched data available. Run Fleet Intelligence Processor first.",
            }

        df = pd.read_parquet(self.cache_path)
        total = len(df)

        # ----------------------------------------------------------
        # Calculate per-field coverage
        # ----------------------------------------------------------
        field_coverage = {}
        for canonical, tag_keys in self.FIELD_GROUPS.items():
            covered = 0
            for _, row in df.iterrows():
                tags = self._parse_tags(row.get("all_tags", "{}"))
                has_value = False
                for key in tag_keys:
                    val = str(tags.get(key, "")).strip()
                    if val and val not in ("", "nan", "None"):
                        has_value = True
                        break
                if has_value:
                    covered += 1

            pct = round((covered / total * 100) if total > 0 else 0, 1)
            field_coverage[canonical] = {
                "count": covered,
                "pct": pct,
                "missing": total - covered,
            }

        # ----------------------------------------------------------
        # Health score = env tag coverage (most important for governance)
        # ----------------------------------------------------------
        env_coverage = field_coverage.get("env", {}).get("pct", 0.0)
        health_score = round(env_coverage, 1)

        # ----------------------------------------------------------
        # Untagged instances (no env tag) sorted by monthly cost desc
        # ----------------------------------------------------------
        untagged = []
        unattributed_90d = 0.0

        for _, row in df.iterrows():
            tags = self._parse_tags(row.get("all_tags", "{}"))
            has_env = False
            for key in self.FIELD_GROUPS["env"]:
                val = str(tags.get(key, "")).strip()
                if val and val not in ("", "nan", "None"):
                    has_env = True
                    break

            if not has_env:
                cost_90d = row.get("total_cost_90d", 0.0) or 0.0
                monthly = row.get("monthly_cost_est", 0.0) or 0.0
                unattributed_90d += cost_90d

                # Determine which tags are missing
                missing = []
                for canonical, keys in self.FIELD_GROUPS.items():
                    has_field = False
                    for key in keys:
                        val = str(tags.get(key, "")).strip()
                        if val and val not in ("", "nan", "None"):
                            has_field = True
                            break
                    if not has_field:
                        missing.append(canonical)

                untagged.append({
                    "resource_id": row.get("resource_id", ""),
                    "resource_name": row.get("resource_name", ""),
                    "instance_type": row.get("instance_type", ""),
                    "region": row.get("region", ""),
                    "monthly_cost": round(monthly, 2),
                    "total_cost_90d": round(cost_90d, 2),
                    "missing_tags": missing,
                    "suggested_env": row.get("inferred_env", "unknown"),
                    "confidence": row.get("tag_confidence", 0.0),
                })

        # Sort by monthly cost descending
        untagged.sort(key=lambda x: -(x.get("monthly_cost") or 0))

        unattributed_monthly = round(unattributed_90d / 89 * 30, 2)

        return {
            "total_instances": total,
            "health_score_pct": health_score,
            "field_coverage": field_coverage,
            "untagged_instances": untagged,
            "unattributed_spend_90d": round(unattributed_90d, 2),
            "unattributed_spend_monthly": unattributed_monthly,
            "generated_at": datetime.utcnow().isoformat(),
        }

    def export_csv(self, output_dir: str = "exports") -> str:
        """
        Export the tag audit to a CSV file.

        Returns the path to the generated CSV.
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(output_dir, f"tag_audit_{timestamp}.csv")

        if not os.path.exists(self.cache_path):
            return ""

        df = pd.read_parquet(self.cache_path)

        # Select and order columns for the CSV
        export_cols = [
            "resource_id", "resource_name", "instance_type", "region",
            "pricing_model", "monthly_cost_est", "total_cost_90d",
            "environment", "owner", "team", "inferred_env",
            "tag_confidence", "tag_source", "safety_tier",
            "has_performance_data", "is_spot_eligible",
        ]
        available_cols = [c for c in export_cols if c in df.columns]
        export_df = df[available_cols].sort_values("monthly_cost_est", ascending=False)
        export_df.to_csv(csv_path, index=False)

        return csv_path

    def _parse_tags(self, raw) -> dict:
        """Parse all_tags JSON string to dict."""
        if pd.isna(raw) or not raw:
            return {}
        try:
            if isinstance(raw, dict):
                return raw
            return json.loads(str(raw))
        except Exception:
            return {}
