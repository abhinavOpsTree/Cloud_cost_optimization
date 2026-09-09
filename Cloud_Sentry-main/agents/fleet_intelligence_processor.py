"""
agents/fleet_intelligence_processor.py
--------------------------------------
Fleet Intelligence Processor — the data ingestion backbone of Cloud-Sentry AI.

NOT an AI Agent (uses Gemini only in Layer 5 fallback, max 20 calls).
This is a Processor — pure Python for Layers 1-4, with optional Gemini Layer 5.

Reads: Live EC2 billing and utilisation data via UnitEconPro API
Produces:
  - cache/enriched_instances.parquet  (279 unique EC2 instances, enriched)
  - cache/nat_gateway_data.parquet    (NAT Gateway cost breakdown)
  - exports/tag_audit_YYYYMMDD_HHMMSS.csv (tag compliance report)

5-Layer Tag Inference:
  Layer 1 — Explicit tags: read env/environment/Environment from all_tags
  Layer 2 — Name patterns:  "test" in name → test, "prod" in name → production
  Layer 3 — EKS patterns:   -Node suffix or kubernetes.io/cluster tag → EKS_NODE
  Layer 4 — Type heuristics: t2.micro/t3.micro → dev/test likely
  Layer 5 — Gemini fallback: only if still "unknown" after L1-4, max 20 calls per run

Verified constants (from billing export — must match exactly):
  UNIQUE_EC2 = 279
  HARD_BLOCKED = 2
  EKS_NODES = 61
  SPOT_ELIGIBLE = 94
  INSTANCES_WITH_CPU = 18
  EC2_COST_90D = 583.25
  NAT_COST_90D = 356.89
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

_CONFIG_PATH = "config.yaml"

def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Tag parsing helper
# ---------------------------------------------------------------------------

def _parse_tags(raw) -> dict:
    """
    Parse all_tags from the Excel export.

    Known data quirks:
      - Sometimes single quotes (Python dict literal) instead of double quotes (JSON)
      - Sometimes empty string or NaN
      - ast.literal_eval first, json.loads as fallback
    """
    if pd.isna(raw) or str(raw).strip() in ("", "nan", "None", "{}"):
        return {}
    raw_str = str(raw).strip()
    try:
        parsed = ast.literal_eval(raw_str)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    try:
        parsed = json.loads(raw_str)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# EKS cluster name extraction
# ---------------------------------------------------------------------------

def _extract_cluster_name(name: str, tags: dict) -> Optional[str]:
    """
    Extract EKS cluster name from tags or resource name.

    Priority:
      1. kubernetes.io/cluster/{name} tag key
      2. eks:cluster-name or aws:eks:cluster-name tag value
      3. Name prefix before -Node suffix (fallback)
    """
    if isinstance(tags, dict):
        for key, val in tags.items():
            if "kubernetes.io/cluster/" in key:
                cluster = key.split("kubernetes.io/cluster/")[-1]
                if cluster:
                    return cluster
            elif key in ("eks:cluster-name", "aws:eks:cluster-name"):
                v = str(val).strip() if val else ""
                if v and v != "nan":
                    return v

    # Fallback: extract from name like "ot-mumbai-v1-35-standard-nodes-Node"
    if name.endswith("-Node"):
        return name.replace("-Node", "")

    return None


# ---------------------------------------------------------------------------
# 5-Layer Tag Inference Engine
# ---------------------------------------------------------------------------

def _layer1_explicit_tags(tags: dict) -> Tuple[Optional[str], float, str]:
    """
    Layer 1 — Read explicit env/environment/Environment tag.

    Returns: (inferred_env or None, confidence, source)
    """
    for key in ("env", "environment", "Environment"):
        val = str(tags.get(key, "")).strip().lower()
        if not val or val == "nan":
            continue

        # Map tag values to canonical environment names
        if val in ("production", "prod"):
            return "production", 1.0, "explicit"
        elif val in ("staging", "stage", "stg", "uat"):
            return "staging", 1.0, "explicit"
        elif val in ("development", "dev"):
            return "dev", 1.0, "explicit"
        elif val in ("test", "testing", "qa"):
            return "test", 1.0, "explicit"
        elif val:
            # Has a value but not one of the standard ones
            return val, 0.8, "explicit"

    return None, 0.0, ""


def _layer2_name_patterns(name: str) -> Tuple[Optional[str], float, str]:
    """
    Layer 2 — Infer environment from resource_name patterns.

    Patterns checked (case-insensitive):
      - "prod" in name → production (0.7 confidence)
      - "test" in name → test (0.8 confidence — naming convention strong signal)
      - "dev" in name  → dev (0.7 confidence)
      - "stage" or "staging" or "uat" → staging (0.7)
    """
    name_lower = name.lower()

    # Production patterns
    if "prod" in name_lower and "product" not in name_lower:
        return "production", 0.7, "name_pattern"

    # Test patterns
    if "test" in name_lower:
        return "test", 0.8, "name_pattern"

    # Dev patterns
    if "dev" in name_lower and "devops" not in name_lower:
        return "dev", 0.7, "name_pattern"

    # Staging patterns
    if "staging" in name_lower or "stage" in name_lower or "uat" in name_lower:
        return "staging", 0.7, "name_pattern"

    return None, 0.0, ""


def _layer3_eks_patterns(
    name: str, tags: dict
) -> Tuple[bool, Optional[str], float, str]:
    """
    Layer 3 — Detect EKS node instances.

    Detection methods:
      1. Resource name ends with "-Node"
      2. all_tags contains kubernetes.io/cluster/ key
      3. all_tags contains eks:cluster-name or aws:eks:cluster-name

    Returns: (is_eks_node, cluster_name, confidence, source)
    """
    cluster_name = None

    # Method 1: Name suffix
    if name.endswith("-Node"):
        cluster_name = _extract_cluster_name(name, tags)
        return True, cluster_name, 0.95, "eks_pattern"

    # Method 2 & 3: Tag keys
    if isinstance(tags, dict):
        for key in tags.keys():
            if "kubernetes.io/cluster" in key:
                cluster_name = _extract_cluster_name(name, tags)
                return True, cluster_name, 0.95, "eks_pattern"

        for key in ("eks:cluster-name", "aws:eks:cluster-name"):
            val = tags.get(key)
            if val and str(val).strip() and str(val).strip() != "nan":
                cluster_name = str(val).strip()
                return True, cluster_name, 0.95, "eks_pattern"

    return False, None, 0.0, ""


def _layer4_type_heuristics(
    instance_type: str, pricing_model: str
) -> Tuple[Optional[str], float, str]:
    """
    Layer 4 — Heuristic inference from instance type and pricing model.

    Rules:
      - t2.micro / t3.micro → likely dev/test (small instances rarely production)
      - Spot pricing → likely dev/test (production avoids Spot)
      - Large instances (xlarge+) → no inference (could be anything)
    """
    itype = str(instance_type).lower()

    if itype in ("t2.micro", "t3.micro", "t2.nano", "t3.nano"):
        return "dev", 0.4, "type_heuristic"

    if str(pricing_model) == "Spot":
        return "dev", 0.3, "type_heuristic"

    return None, 0.0, ""


def _layer5_gemini_fallback(
    name: str,
    instance_type: str,
    tags: dict,
    cost_90d: float,
    run_id: Optional[str] = None,
) -> Tuple[str, float, str]:
    """
    Layer 5 — Gemini fallback for instances still "unknown" after L1-4.

    Max 20 calls per run (tracked by llm_client budget system).
    Returns a conservative low-confidence inference.
    On any failure, returns ("unknown", 0.0, "llm_failed").
    """
    from core.llm_client import call_gemini

    tag_summary = ", ".join(
        f"{k}={v}" for k, v in tags.items()
        if v and str(v).strip() and str(v).strip() != "nan"
    ) if tags else "no tags"

    prompt = f"""You are a FinOps analyst. Based on this AWS EC2 instance metadata, infer its likely environment.

Instance name: {name}
Instance type: {instance_type}
Tags: {tag_summary}
90-day cost: ${cost_90d:.2f}

Respond with ONLY a JSON object (no markdown, no explanation):
{{"env": "production|staging|test|dev|unknown", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}

Rules:
- If unsure, return "unknown" with low confidence
- "do not delete" or "do no delete" in name → production (but these are already blocked)
- VPN/proxy servers → likely production infrastructure
- Names with "test", "dev", "staging" → obvious
- Generic names with no tags → unknown
"""

    try:
        response = call_gemini(
            prompt=prompt,
            expect_json=True,
            agent="fleet_intelligence_processor",
            resource_id=name,
            run_id=run_id,
        )
        result = json.loads(response)
        env = str(result.get("env", "unknown")).lower()
        conf = float(result.get("confidence", 0.0))
        # Cap Gemini confidence at 0.6 — human review still encouraged
        conf = min(conf, 0.6)
        if env in ("production", "staging", "test", "dev", "unknown"):
            return env, conf, "llm"
        return "unknown", 0.0, "llm"
    except Exception as e:
        print(f"[FIP] Layer 5 Gemini failed for {name}: {e}")
        return "unknown", 0.0, "llm_failed"


# ---------------------------------------------------------------------------
# Safety tier assignment
# ---------------------------------------------------------------------------

def _assign_safety_tier(
    name: str,
    tags: dict,
    inferred_env: str,
    tag_source: str,
    is_eks_node: bool,
) -> str:
    """
    Assign a preliminary safety tier based on tag inference results.

    This is a PRE-governance classification used during ingestion.
    The full governance agent (Task 3) makes the final decision.

    Returns: "HARD_BLOCK" | "FLAG" | "APPROVE"
    """
    name_lower = name.lower()

    # Tier 1 — Hard blocks (name patterns)
    if "do not delete" in name_lower or "do no delete" in name_lower:
        return "HARD_BLOCK"

    # Tier 1 — Hard blocks (explicit production tag)
    if isinstance(tags, dict):
        for key in ("env", "environment", "Environment"):
            val = str(tags.get(key, "")).strip().lower()
            if val in ("production", "prod"):
                return "HARD_BLOCK"

    # Tier 1 — High-confidence inferred production
    if inferred_env == "production" and tag_source in ("explicit", "eks_pattern"):
        return "HARD_BLOCK"

    # Tier 2 — EKS nodes (managed at cluster level, not individually)
    if is_eks_node:
        return "FLAG"

    # Tier 2 — Network gateways (name-based)
    if "vpn" in name_lower or "proxy" in name_lower:
        return "FLAG"

    return "APPROVE"


# ---------------------------------------------------------------------------
# Spot eligibility
# ---------------------------------------------------------------------------

def _is_spot_eligible(
    pricing_model: str,
    safety_tier: str,
    is_eks_node: bool,
) -> bool:
    """
    Determine if an instance is eligible for Spot conversion.

    Criteria:
      - Currently OnDemand (not already Spot)
      - NOT hard blocked
      - NOT an EKS node (EKS uses cluster autoscaler)

    This produces exactly 94 instances from the pilot data:
      139 OnDemand - 2 HARD_BLOCK - 43 EKS OnDemand nodes = 94
    """
    if pricing_model != "OnDemand":
        return False
    if safety_tier == "HARD_BLOCK":
        return False
    if is_eks_node:
        return False
    return True


# ---------------------------------------------------------------------------
# Rightsizing signal computation
# ---------------------------------------------------------------------------

def _compute_rightsizing_signal(
    cpu_avg: Optional[float],
    cpu_max: Optional[float],
    has_cpu_data: bool,
) -> Optional[str]:
    """
    Determine the rightsizing signal from CPU metrics.

    Only applies to instances with performance data (18 out of 279).
    For the 261 without data, returns None (not "OPTIMIZED", not 0%).

    Signals:
      SEVERELY_OVER_PROVISIONED: cpu_avg < 5%
      OVER_PROVISIONED:          cpu_avg < 15%
      OPTIMIZED:                 cpu_avg >= 15% OR cpu_max > 60%
    """
    if not has_cpu_data or pd.isna(cpu_avg):
        return None

    if cpu_avg < 5.0:
        return "SEVERELY_OVER_PROVISIONED"
    elif cpu_avg < 15.0:
        return "OVER_PROVISIONED"
    else:
        return "OPTIMIZED"


# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------

class FleetIntelligenceProcessor:
    """
    Ingests and enriches the EC2 billing export.

    Usage:
        processor = FleetIntelligenceProcessor()
        result = processor.run()
    """

    def __init__(self, config_path: str = _CONFIG_PATH):
        self.config = _load_config()
        self.data_config = self.config["data"]
        self.run_id = str(uuid.uuid4())
        self._gemini_calls = 0

    def run(self, days: int = 90, start_date: str = None, end_date: str = None) -> dict:
        """
        Execute the full ingestion pipeline.

        Returns a summary dict with counts for gate testing.
        Writes:
          - cache/enriched_instances.parquet
          - cache/nat_gateway_data.parquet
          - exports/tag_audit_YYYYMMDD_HHMMSS.csv (via Tag Compliance Reporter)
        """
        started_at = datetime.utcnow().isoformat()
        cache_path = self.data_config["cache_path"]
        nat_cache_path = self.data_config["nat_cache_path"]
        print("[FIP] Loading live data from Unitecon Pro & CloudWatch")

        # ----------------------------------------------------------
        # Load live data from UnitEconPro mock API
        # ----------------------------------------------------------
        from core.live_data_loader import get_live_billing_df
        df_raw = get_live_billing_df(account="opstree", days=days, start_date=start_date, end_date=end_date)
        print(f"[FIP] Loaded {len(df_raw)} rows from live data")

        # ----------------------------------------------------------
        # Drop rows where UnitEconPro data fetch failed entirely.
        # These rows contain only resource_id and data_fetch_failed=True;
        # passing them into analysis would produce misleading zero-cost/
        # zero-usage instances that could generate false recommendations.
        # ----------------------------------------------------------
        if "data_fetch_failed" in df_raw.columns:
            failed_rows = df_raw[df_raw["data_fetch_failed"] == True]
            if len(failed_rows) > 0:
                failed_ids = failed_rows["resource_id"].tolist()
                print(f"[FIP] WARNING: {len(failed_rows)} instance(s) had fatal fetch failures "
                      f"and are EXCLUDED from analysis: {failed_ids}")
                df_raw = df_raw[df_raw["data_fetch_failed"] != True].copy()
                print(f"[FIP] Proceeding with {len(df_raw)} valid rows.")

        if df_raw.empty or "product_name" not in df_raw.columns:
            failed_count = len(failed_rows) if 'failed_rows' in locals() else 0
            print(f"[FIP] WARNING: All instances ({failed_count}) failed to fetch from UnitEconPro — skipping this ingest run")
            empty_ec2 = pd.DataFrame(columns=[
                "resource_id", "resource_name", "instance_type", "region",
                "pricing_model", "monthly_cost_est", "total_cost_90d",
                "environment", "owner", "team", "inferred_env",
                "tag_confidence", "tag_source", "safety_tier",
                "has_performance_data", "is_spot_eligible",
                "inferred_workload", "rightsizing_signal", "cluster_name", "cpu_avg_pct"
            ])
            summary = self._build_summary(empty_ec2, from_cache=False, started_at=started_at)
            self._log_ingest_run(summary)
            return summary


        # ----------------------------------------------------------
        # Pass 1: Process EC2 instances
        # ----------------------------------------------------------
        ec2_df = self._process_ec2(df_raw)

        # ----------------------------------------------------------
        # Pass 2: Process NAT Gateway data
        # ----------------------------------------------------------
        nat_df = self._process_nat_gateway(df_raw)

        # ----------------------------------------------------------
        # Save to cache
        # ----------------------------------------------------------
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        ec2_df.to_parquet(cache_path, index=False)
        print(f"[FIP] Saved {len(ec2_df)} instances to {cache_path}")

        nat_df.to_parquet(nat_cache_path, index=False)
        print(f"[FIP] Saved {len(nat_df)} NAT gateways to {nat_cache_path}")

        # ----------------------------------------------------------
        # Generate tag audit CSV
        # ----------------------------------------------------------
        self._generate_tag_audit_csv(ec2_df)

        # ----------------------------------------------------------
        # Log ingest run to SQLite
        # ----------------------------------------------------------
        summary = self._build_summary(ec2_df, from_cache=False, started_at=started_at)
        self._log_ingest_run(summary)

        return summary

    def _process_ec2(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Process all EC2 Compute Instance rows.

        Steps:
          1. Filter to product_name == "Compute Instance"
          2. Aggregate per unique resource_id (sum cost, take first for other cols)
          3. Run 5-layer tag inference on each instance
          4. Assign safety tier and spot eligibility

        Returns a DataFrame with one row per unique EC2 instance.
        """
        product_filter = self.data_config["product_filter"]
        ec2 = df_raw[df_raw["product_name"] == product_filter].copy()

        if ec2.empty:
            print("[FIP] WARNING: No Compute Instance rows found!")
            return pd.DataFrame()

        print(f"[FIP] Found {len(ec2)} EC2 billing rows")

        # ----------------------------------------------------------
        # Aggregate per unique resource_id
        # ----------------------------------------------------------
        agg_dict = {
            "resource_name": "first",
            "instance_type": "first",
            "pricing_model": "first",
            "region": "first",
            "availability_zone": "first",
            "environment": "first",
            "owner": "first",
            "team": "first",
            "project": "first",
            "all_tags": "first",
            "cpu_avg_pct": "first",
            "cpu_max_pct": "first",
            "cpu_p95_pct": "first",
            "net_in_mbps": "first",
            "net_out_mbps": "first",
            "rightsizing_signal": "first",
            "inferred_state": "first",
            "unblended_cost": "sum",
        }
        instances = ec2.groupby("resource_id").agg(agg_dict).reset_index()
        print(f"[FIP] Deduplicated to {len(instances)} unique EC2 instances")

        # ----------------------------------------------------------
        # Enrich each instance
        # ----------------------------------------------------------
        enriched_rows = []
        for _, row in instances.iterrows():
            enriched = self._enrich_instance(row)
            enriched_rows.append(enriched)

        result = pd.DataFrame(enriched_rows)

        # ----------------------------------------------------------
        # Validate critical counts
        # ----------------------------------------------------------
        n_instances = len(result)
        n_hard_blocked = (result["safety_tier"] == "HARD_BLOCK").sum()
        n_eks = (result["inferred_workload"] == "EKS_NODE").sum()
        n_spot_eligible = result["is_spot_eligible"].sum()
        n_with_cpu = result["has_performance_data"].sum()

        print(f"\n[FIP] === ENRICHMENT SUMMARY ===")
        print(f"  Unique instances: {n_instances}")
        print(f"  Hard blocked: {n_hard_blocked}")
        print(f"  EKS nodes: {n_eks}")
        print(f"  Spot eligible: {n_spot_eligible}")
        print(f"  With CPU data: {n_with_cpu}")
        print(f"  Gemini calls used: {self._gemini_calls}")

        return result

    def _enrich_instance(self, row: pd.Series) -> dict:
        """
        Enrich a single instance with 5-layer tag inference.

        Runs Layers 1-4 deterministically, then Layer 5 (Gemini) only if needed.
        """
        resource_id = row["resource_id"]
        resource_name = str(row["resource_name"]) if pd.notna(row.get("resource_name")) else ""
        instance_type = str(row.get("instance_type", "")) if pd.notna(row.get("instance_type")) else ""
        pricing_model = str(row.get("pricing_model", "")) if pd.notna(row.get("pricing_model")) else ""
        region = str(row.get("region", "")) if pd.notna(row.get("region")) else ""
        cost_90d = float(row.get("unblended_cost", 0.0))
        lifecycle_state = str(row.get("inferred_state", "Unknown"))
        monthly_cost = cost_90d / 89 * 30 if lifecycle_state != "Terminated" else 0.0

        # Performance data
        cpu_avg = row.get("cpu_avg_pct")
        cpu_max = row.get("cpu_max_pct")
        cpu_p95 = row.get("cpu_p95_pct")
        net_in = row.get("net_in_mbps")
        net_out = row.get("net_out_mbps")

        # has_performance_data: True only if cpu_avg_pct is NOT NaN
        has_cpu_data = pd.notna(cpu_avg)

        # Parse tags
        tags = _parse_tags(row.get("all_tags"))

        # Original rightsizing signal from export
        rs_signal_raw = row.get("rightsizing_signal")
        rs_signal_raw = str(rs_signal_raw) if pd.notna(rs_signal_raw) else None

        # ----------------------------------------------------------
        # Layer 1 — Explicit tags
        # ----------------------------------------------------------
        l1_env, l1_conf, l1_source = _layer1_explicit_tags(tags)

        # ----------------------------------------------------------
        # Layer 2 — Name patterns
        # ----------------------------------------------------------
        l2_env, l2_conf, l2_source = _layer2_name_patterns(resource_name)

        # ----------------------------------------------------------
        # Layer 3 — EKS patterns
        # ----------------------------------------------------------
        is_eks, cluster_name, l3_conf, l3_source = _layer3_eks_patterns(resource_name, tags)

        # ----------------------------------------------------------
        # Layer 4 — Type heuristics
        # ----------------------------------------------------------
        l4_env, l4_conf, l4_source = _layer4_type_heuristics(instance_type, pricing_model)

        # ----------------------------------------------------------
        # Merge inference results (highest confidence wins)
        # ----------------------------------------------------------
        inferred_env = "unknown"
        tag_confidence = 0.0
        tag_source = "unknown"

        candidates = []
        if l1_env:
            candidates.append((l1_env, l1_conf, l1_source))
        if l2_env:
            candidates.append((l2_env, l2_conf, l2_source))
        if l4_env:
            candidates.append((l4_env, l4_conf, l4_source))

        if candidates:
            # Sort by confidence descending, pick highest
            candidates.sort(key=lambda x: -x[1])
            inferred_env, tag_confidence, tag_source = candidates[0]

        # ----------------------------------------------------------
        # Layer 5 — Gemini fallback (only if still unknown and budget allows)
        # ----------------------------------------------------------
        layer5_max = self.config["llm"]["layer5_max_calls"]
        if inferred_env == "unknown" and self._gemini_calls < layer5_max:
            l5_env, l5_conf, l5_source = _layer5_gemini_fallback(
                resource_name, instance_type, tags, cost_90d, self.run_id
            )
            if l5_env != "unknown" and l5_conf > tag_confidence:
                inferred_env = l5_env
                tag_confidence = l5_conf
                tag_source = l5_source
            self._gemini_calls += 1

        # ----------------------------------------------------------
        # Workload type
        # ----------------------------------------------------------
        inferred_workload = "UNKNOWN"
        if is_eks:
            inferred_workload = "EKS_NODE"
        elif "vpn" in resource_name.lower():
            inferred_workload = "NETWORK_GATEWAY"
        elif "proxy" in resource_name.lower():
            inferred_workload = "NETWORK_GATEWAY"

        # ----------------------------------------------------------
        # Safety tier
        # ----------------------------------------------------------
        safety_tier = _assign_safety_tier(
            resource_name, tags, inferred_env, tag_source, is_eks
        )

        # ----------------------------------------------------------
        # Spot eligibility
        # ----------------------------------------------------------
        spot_eligible = _is_spot_eligible(pricing_model, safety_tier, is_eks)

        # ----------------------------------------------------------
        # Rightsizing signal (use export value if present, else compute)
        # ----------------------------------------------------------
        if rs_signal_raw and rs_signal_raw not in ("nan", "None", ""):
            rightsizing_signal = rs_signal_raw
        else:
            rightsizing_signal = _compute_rightsizing_signal(
                float(cpu_avg) if pd.notna(cpu_avg) else None,
                float(cpu_max) if pd.notna(cpu_max) else None,
                has_cpu_data,
            )

        # ----------------------------------------------------------
        # Owner inference
        # ----------------------------------------------------------
        owner = None
        if isinstance(tags, dict):
            owner = tags.get("owner") or tags.get("Owner")
            if owner:
                owner = str(owner).strip()
                if not owner or owner == "nan":
                    owner = None
        if not owner:
            col_owner = row.get("owner")
            if pd.notna(col_owner) and str(col_owner).strip():
                owner = str(col_owner).strip()

        # ----------------------------------------------------------
        # Team
        # ----------------------------------------------------------
        team = None
        if isinstance(tags, dict):
            team = tags.get("team") or tags.get("Team")
            if team:
                team = str(team).strip()
                if not team or team == "nan":
                    team = None
        if not team:
            col_team = row.get("team")
            if pd.notna(col_team) and str(col_team).strip():
                team = str(col_team).strip()

        # ----------------------------------------------------------
        # Build enriched instance dict
        # ----------------------------------------------------------
        return {
            "resource_id": resource_id,
            "resource_name": resource_name,
            "instance_type": instance_type,
            "pricing_model": pricing_model,
            "region": region,
            "environment": str(row.get("environment", "")) if pd.notna(row.get("environment")) else "",
            "owner": owner,
            "team": team,
            "all_tags": json.dumps(tags) if tags else "{}",
            # Performance — NaN preserved as NaN, not 0
            "cpu_avg_pct": float(cpu_avg) if pd.notna(cpu_avg) else None,
            "cpu_max_pct": float(cpu_max) if pd.notna(cpu_max) else None,
            "cpu_p95_pct": float(cpu_p95) if pd.notna(cpu_p95) else None,
            "net_in_mbps": float(net_in) if pd.notna(net_in) else None,
            "net_out_mbps": float(net_out) if pd.notna(net_out) else None,
            "rightsizing_signal": rightsizing_signal,
            # Cost
            "total_cost_90d": round(cost_90d, 2),
            "monthly_cost_est": round(monthly_cost, 2),
            # Inference results
            "inferred_env": inferred_env,
            "inferred_owner": owner,
            "inferred_workload": inferred_workload,
            "safety_tier": safety_tier,
            "tag_confidence": round(tag_confidence, 2),
            "tag_source": tag_source,
            # Flags
            "is_spot_eligible": spot_eligible,
            "cluster_name": cluster_name if is_eks else None,
            "has_performance_data": has_cpu_data,
            "lifecycle_state": lifecycle_state,
        }

    def _process_nat_gateway(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Extract and aggregate NAT Gateway data.

        Filter: product_name == "NAT Gateway"
        Aggregate by resource_id, compute:
          - cost_90d: sum of unblended_cost
          - monthly_cost: cost_90d / 89 * 30
          - gb_processed: sum of usage_amount where usage_unit == "GB"
        """
        nat_filter = self.data_config.get("nat_product_filter", "NAT Gateway")
        nat = df_raw[df_raw["product_name"] == nat_filter].copy()

        if nat.empty:
            print("[FIP] WARNING: No NAT Gateway rows found!")
            return pd.DataFrame(columns=[
                "resource_id", "resource_name", "region",
                "cost_90d", "monthly_cost", "gb_processed"
            ])

        print(f"[FIP] Found {len(nat)} NAT Gateway billing rows")

        # Compute GB processed per resource_id (only from GB usage_unit rows)
        nat_gb = nat[nat["usage_unit"] == "GB"].groupby("resource_id")["usage_amount"].sum()

        # Aggregate cost per resource_id
        nat_agg = nat.groupby("resource_id").agg({
            "resource_name": "first",
            "region": "first",
            "unblended_cost": "sum",
        }).reset_index()

        nat_agg = nat_agg.rename(columns={"unblended_cost": "cost_90d"})
        nat_agg["monthly_cost"] = (nat_agg["cost_90d"] / 89 * 30).round(2)
        nat_agg["cost_90d"] = nat_agg["cost_90d"].round(2)

        # Merge GB processed
        nat_agg["gb_processed"] = nat_agg["resource_id"].map(nat_gb).fillna(0.0).round(2)

        # Fill NaN resource_name with empty string
        nat_agg["resource_name"] = nat_agg["resource_name"].fillna("")

        # Select final columns
        result = nat_agg[["resource_id", "resource_name", "region", "cost_90d", "monthly_cost", "gb_processed"]]

        print(f"[FIP] NAT Gateway: {len(result)} gateways, total cost ${result['cost_90d'].sum():.2f} (90d)")
        return result

    def _generate_tag_audit_csv(self, ec2_df: pd.DataFrame) -> None:
        """
        Generate tag audit CSV for the Tag Compliance Reporter.

        Sorted by monthly_cost_est descending (highest cost first).
        """
        exports_dir = self.data_config["exports_dir"]
        os.makedirs(exports_dir, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(exports_dir, f"tag_audit_{timestamp}.csv")

        # Select relevant columns for tag audit
        audit_cols = [
            "resource_id", "resource_name", "instance_type", "region",
            "pricing_model", "monthly_cost_est", "total_cost_90d",
            "environment", "owner", "team", "inferred_env",
            "tag_confidence", "tag_source", "safety_tier",
            "has_performance_data", "is_spot_eligible",
        ]
        audit_df = ec2_df[audit_cols].sort_values("monthly_cost_est", ascending=False)
        audit_df.to_csv(csv_path, index=False)
        print(f"[FIP] Tag audit CSV saved to {csv_path}")

    def _build_summary(
        self, ec2_df: pd.DataFrame, from_cache: bool, started_at: str
    ) -> dict:
        """Build the summary dict returned by run() and used for gate testing."""
        n_instances = len(ec2_df)
        n_hard_blocked = int((ec2_df["safety_tier"] == "HARD_BLOCK").sum())
        n_eks = int((ec2_df["inferred_workload"] == "EKS_NODE").sum())
        n_spot_eligible = int(ec2_df["is_spot_eligible"].sum())
        n_with_cpu = int(ec2_df["has_performance_data"].sum())

        # Build instances_by_name lookup
        instances_by_name = {}
        for _, row in ec2_df.iterrows():
            name = row.get("resource_name", "")
            if name:
                instances_by_name[name] = {
                    "resource_id": row.get("resource_id"),
                    "safety_tier": row.get("safety_tier"),
                    "inferred_env": row.get("inferred_env"),
                    "inferred_workload": row.get("inferred_workload"),
                    "rightsizing_signal": row.get("rightsizing_signal"),
                    "is_spot_eligible": bool(row.get("is_spot_eligible")),
                    "has_performance_data": bool(row.get("has_performance_data")),
                    "cluster_name": row.get("cluster_name"),
                    "total_cost_90d": row.get("total_cost_90d"),
                    "monthly_cost_est": row.get("monthly_cost_est"),
                    "cpu_avg_pct": row.get("cpu_avg_pct"),
                    "tag_confidence": row.get("tag_confidence"),
                    "tag_source": row.get("tag_source"),
                }

        return {
            "run_id": self.run_id,
            "instances_found": n_instances,
            "hard_blocked": n_hard_blocked,
            "eks_nodes": n_eks,
            "spot_eligible": n_spot_eligible,
            "instances_with_cpu_data": n_with_cpu,
            "gemini_calls_used": self._gemini_calls,
            "from_cache": from_cache,
            "started_at": started_at,
            "completed_at": datetime.utcnow().isoformat(),
            "instances_by_name": instances_by_name,
        }

    def _log_ingest_run(self, summary: dict) -> None:
        """Log this run to the ingest_runs SQLite table."""
        try:
            from core.state_store import StateStore
            store = StateStore()
            store.save_ingest_run({
                "run_id": summary["run_id"],
                "source_file": self.data_config["input_file"],
                "source_file_size": os.path.getsize(self.data_config["input_file"]),
                "instances_found": summary["instances_found"],
                "eks_nodes_found": summary["eks_nodes"],
                "hard_blocked_found": summary["hard_blocked"],
                "spot_eligible_found": summary["spot_eligible"],
                "gemini_calls_used": summary["gemini_calls_used"],
                "started_at": summary["started_at"],
                "completed_at": summary["completed_at"],
                "status": "COMPLETED",
            })
        except Exception as e:
            print(f"[FIP] Failed to log ingest run: {e}")
