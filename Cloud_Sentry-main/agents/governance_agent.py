"""
agents/governance_agent.py
---------------------------
Governance Agent — evaluates all instances through the 3-tier governance cascade.

This IS an AI Agent (Tier 3 uses Gemini).

Governance cascade (strict order, first result wins):
  Tier 1 — ProductionShieldSkill   (pure Python — hard blocks)
  Tier 2 — RiskFlaggingSkill       (pure Python — risk flags)
  Tier 3 — AmbiguousReasoningSkill (Gemini — ambiguous cases)

Rules:
  - Tiers run in order 1 → 2 → 3
  - First tier to return a non-None result wins
  - Tier 3 CANNOT override Tier 1 or Tier 2 decisions
  - Every decision is logged to SQLite with reason AND tier
  - BLOCKED is permanent — no UI override exists
  - FLAGGED requires human checkbox confirmation before Execute
  - Hard stop at 50 Gemini calls per run — remaining get FLAGGED

Memory:
  - Reads governance_decisions table for Tier 3 cache (7-day validity)
  - Writes every decision to governance_decisions (audit trail)
  - Updates recommendations table status to BLOCKED/FLAGGED/APPROVED
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from skills.governance.production_shield import ProductionShieldSkill
from skills.governance.risk_flagging import RiskFlaggingSkill
from skills.governance.ambiguous_reasoning import AmbiguousReasoningSkill


class GovernanceAgent:
    """
    Evaluates all instances through the 3-tier governance cascade.

    Usage:
        agent = GovernanceAgent()
        decisions = agent.evaluate_all()
        # decisions = {resource_id: {status, tier, reason, ...}, ...}
        # Use agent.get_by_name(name) for name-based lookup
    """

    def __init__(self):
        # Instantiate governance skills in tier order
        self.tier1 = ProductionShieldSkill()
        self.tier2 = RiskFlaggingSkill()
        self.tier3 = AmbiguousReasoningSkill()

    def evaluate_all(
        self,
        cache_path: str = "cache/enriched_instances.parquet",
        run_id: Optional[str] = None,
    ) -> Dict[str, dict]:
        """
        Run governance evaluation on ALL enriched instances.

        Args:
            cache_path: Path to enriched_instances.parquet
            run_id: Current analysis run ID (for SQLite logging)

        Returns:
            Dict keyed by resource_id (unique), each value is:
            {
                "resource_id": str,
                "resource_name": str,
                "status": "BLOCKED" | "FLAGGED" | "APPROVED",
                "tier": 1 | 2 | 3,
                "reason": str,
                "inferred_workload": str,
                "gemini_assessment": dict | None,
            }

        Also populates self._by_name for name-based lookup.
        """
        if not os.path.exists(cache_path):
            print("[GOV] ERROR: enriched_instances.parquet not found. Run Fleet Intelligence Processor first.")
            return {}

        # Reset LLM budget for this governance run
        try:
            from core.llm_client import reset_run_counters
            reset_run_counters()
        except Exception:
            pass

        df = pd.read_parquet(cache_path)
        print(f"[GOV] Evaluating {len(df)} instances through governance cascade")

        # Sort: named instances first (higher priority for Gemini budget),
        # then by cost descending (expensive instances get Gemini first)
        df["_has_name"] = df["resource_name"].apply(
            lambda x: 0 if (pd.notna(x) and str(x).strip()) else 1
        )
        df = df.sort_values(["_has_name", "monthly_cost_est"], ascending=[True, False])

        decisions = {}
        self._by_name = {}  # name-based lookup
        counts = {"BLOCKED": 0, "FLAGGED": 0, "APPROVED": 0}

        for _, row in df.iterrows():
            instance = row.to_dict()
            resource_name = str(instance.get("resource_name", ""))
            resource_id = str(instance.get("resource_id", ""))

            # Parse all_tags if it's a JSON string
            tags_raw = instance.get("all_tags", "{}")
            if isinstance(tags_raw, str):
                try:
                    instance["all_tags"] = json.loads(tags_raw)
                except Exception:
                    instance["all_tags"] = {}

            # Create a dummy recommendation for governance evaluation
            # (actual recommendations are created by FinOps Analyst in Task 4)
            dummy_rec = {
                "track": "governance_evaluation",
                "action": "Pending analysis",
                "estimated_monthly_saving": 0.0,
            }

            # Run the 3-tier cascade
            decision = self._evaluate_single(instance, dummy_rec)

            # Add resource metadata to decision
            decision["resource_id"] = resource_id
            decision["resource_name"] = resource_name
            decision["inferred_workload"] = str(instance.get("inferred_workload", ""))

            # Key by resource_id (unique) — NOT resource_name (can be duplicate/empty)
            decisions[resource_id] = decision
            # Also build name-based lookup (last-write-wins for duplicates)
            if resource_name:
                self._by_name[resource_name] = decision
            counts[decision["status"]] = counts.get(decision["status"], 0) + 1

            # Log to SQLite
            self._log_decision(decision, run_id)

        print(f"\n[GOV] === GOVERNANCE SUMMARY ===")
        print(f"  BLOCKED:  {counts.get('BLOCKED', 0)}")
        print(f"  FLAGGED:  {counts.get('FLAGGED', 0)}")
        print(f"  APPROVED: {counts.get('APPROVED', 0)}")
        print(f"  Total:    {sum(counts.values())}")

        return decisions

    def get_by_name(self, resource_name: str) -> Optional[dict]:
        """Look up a governance decision by resource_name."""
        return self._by_name.get(resource_name)

    def run(self, **kwargs):
        """Alias for evaluate_all() — API compatibility."""
        return self.evaluate_all(**kwargs)

    def evaluate_single(
        self,
        instance: dict,
        recommendation: dict,
    ) -> dict:
        """
        Evaluate a single instance through the governance cascade.

        Public API for evaluating individual instances (used by FinOps Analyst).

        Args:
            instance: Dict with instance data from enriched_instances.parquet
            recommendation: Dict with recommendation data

        Returns:
            Decision dict with status, tier, reason
        """
        # Parse all_tags if needed
        tags_raw = instance.get("all_tags", "{}")
        if isinstance(tags_raw, str):
            try:
                instance["all_tags"] = json.loads(tags_raw)
            except Exception:
                instance["all_tags"] = {}

        return self._evaluate_single(instance, recommendation)

    def _evaluate_single(self, instance: dict, recommendation: dict) -> dict:
        """
        Internal: run the 3-tier cascade on a single instance.

        Tier 1 → Tier 2 → Tier 3 (first non-None wins).
        """
        resource_name = instance.get("resource_name", "unknown")

        # ---------------------------------------------------------------
        # Tier 1 — Production Shield (hard blocks)
        # ---------------------------------------------------------------
        result = self.tier1.evaluate(instance, recommendation)
        if result is not None:
            print(f"[GOV T1] BLOCKED: {resource_name} — {result['reason']}")
            return result

        # ---------------------------------------------------------------
        # Tier 2 — Risk Flagging
        # ---------------------------------------------------------------
        result = self.tier2.evaluate(instance, recommendation)
        if result is not None:
            # Don't print every EKS node (too noisy), just count
            if "EKS node" not in result.get("reason", ""):
                print(f"[GOV T2] FLAGGED: {resource_name} — {result['reason']}")
            return result

        # ---------------------------------------------------------------
        # Tier 3 — Ambiguous Reasoning (Gemini)
        # Only called if tag_confidence < threshold
        # ---------------------------------------------------------------
        result = self.tier3.evaluate(instance, recommendation)
        if result is not None:
            return result

        # Fallback: if somehow all tiers return None, approve
        # (Tier 3 should always return a result, but safety net)
        return {
            "status": "APPROVED",
            "tier": 3,
            "reason": "Passed all governance checks — approved for optimization",
        }

    def _log_decision(self, decision: dict, run_id: Optional[str] = None) -> None:
        """Log a governance decision to SQLite for audit trail."""
        try:
            from core.state_store import StateStore
            store = StateStore()
            store.save_governance_decision({
                "resource_id": decision.get("resource_id", ""),
                "resource_name": decision.get("resource_name", ""),
                "decision": decision["status"],
                "tier": decision.get("tier"),
                "reason": decision.get("reason", ""),
                "gemini_assessment": decision.get("gemini_assessment"),
                "run_id": run_id,
            })
        except Exception as e:
            print(f"[GOV] Decision logging failed (non-fatal): {e}")
