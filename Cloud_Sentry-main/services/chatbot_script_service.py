"""
services/chatbot_script_service.py
------------------------------------
Chatbot-triggered script generation with full governance enforcement.

Flow:
  1. Find instance by name in enriched parquet
  2. Load existing recommendation from SQLite (if exists) or build one
  3. Run GovernanceAgent — full 3-tier check (Tier 1 + 2 = Python, Tier 3 = Gemini)
  4. If BLOCKED or FLAGGED → return reason, no scripts generated
  5. If APPROVED → call DevOpsRemediationAgent to generate scripts
  6. Save to remediations table with source="chatbot"
  7. Return formatted response for chat display

CRITICAL:
  - Never executes anything on AWS
  - Never bypasses governance
  - Scripts are TEXT ONLY — for engineer review
  - Execution requires dashboard Confirm and Deploy flow
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from agents.governance_agent import GovernanceAgent
from agents.devops_remediation_agent import DevOpsRemediationAgent
from core.state_store import StateStore


PARQUET_PATH = "cache/enriched_instances.parquet"


class ChatbotScriptService:
    """
    Generate governance-checked scripts via chatbot interface.

    The scripts are TEXT for engineer review.
    Actual execution requires the dashboard Execute flow.
    """

    def __init__(self):
        self.governance_agent = GovernanceAgent()
        self.devops_agent = DevOpsRemediationAgent()
        self.store = StateStore()

    def generate_for_instance(self, search_term: str) -> dict:
        """
        Main entry point. Find instance, govern, generate scripts if approved.

        Returns:
            {
                status: "BLOCKED" | "FLAGGED" | "APPROVED" | "NOT_FOUND" | "NO_ACTION_NEEDED" | "ERROR"
                resource_name: str
                governance_reason: str (for BLOCKED/FLAGGED)
                governance_tier: int (1, 2, or 3)
                scripts: dict (for APPROVED only)
                    terraform_hcl: str
                    aws_cli_command: str
                    rollback_command: str
                action: str
                saving_monthly: float
                chat_message: str   # pre-formatted message for display in chat
            }
        """
        # Step 1: Find the instance
        instance = self._find_instance(search_term)
        if instance is None:
            return {
                "status": "NOT_FOUND",
                "chat_message": f"❌ No instance found matching '{search_term}'. Try using the exact name from the Instances tab.",
            }

        resource_name = instance.get("resource_name", search_term)
        resource_id = instance.get("resource_id", "")

        # Step 2: Get or build a recommendation for this instance
        recommendation = self._get_recommendation(resource_id, instance)
        if recommendation is None:
            return {
                "status": "NO_ACTION_NEEDED",
                "resource_name": resource_name,
                "chat_message": f"ℹ️ **{resource_name}** has no optimization recommendations available. "
                                f"It may already be optimised, or lack the performance data needed for analysis.",
            }

        # Step 3: Run FULL governance — same 3-tier check as the dashboard
        # CRITICAL: This MUST use the same GovernanceAgent as the main pipeline
        gov_result = self.governance_agent._evaluate_single(instance, recommendation)
        gov_status = gov_result.get("status", "APPROVED")
        gov_reason = gov_result.get("reason", "")
        gov_tier = gov_result.get("tier")

        # Step 4: BLOCKED — stop immediately, no scripts
        if gov_status == "BLOCKED":
            tier_label = f"Tier {gov_tier}" if gov_tier else "Tier 1"
            return {
                "status": "BLOCKED",
                "resource_name": resource_name,
                "governance_reason": gov_reason,
                "governance_tier": gov_tier,
                "chat_message": (
                    f"🔒 **{resource_name} — HARD BLOCKED ({tier_label})**\n\n"
                    f"{gov_reason}\n\n"
                    f"This protection is enforced in code. No scripts can be generated for this instance."
                ),
            }

        # Step 5: FLAGGED — stop, explain risk
        if gov_status == "FLAGGED":
            tier_label = f"Tier {gov_tier}" if gov_tier else "Tier 2"
            return {
                "status": "FLAGGED",
                "resource_name": resource_name,
                "governance_reason": gov_reason,
                "governance_tier": gov_tier,
                "chat_message": (
                    f"⚠️ **{resource_name} — FLAGGED ({tier_label})**\n\n"
                    f"{gov_reason}\n\n"
                    f"Scripts cannot be generated for flagged instances. "
                    f"Review via the Recommendations tab and tick the acknowledgement checkbox before executing."
                ),
            }

        # Step 6: APPROVED — generate scripts
        try:
            scripts = self.devops_agent.generate(recommendation)
        except Exception as e:
            return {
                "status": "ERROR",
                "resource_name": resource_name,
                "chat_message": f"❌ Script generation failed for **{resource_name}**: {e}",
            }

        # Step 7: Save to SQLite with source="chatbot"
        try:
            remediation_id = str(uuid.uuid4())
            self.store.save_remediation({
                "id": remediation_id,
                "recommendation_id": recommendation.get("id", ""),
                "resource_id": resource_id,
                "resource_name": resource_name,
                "action_taken": recommendation.get("action", ""),
                "terraform_hcl": scripts.get("terraform_hcl", ""),
                "aws_cli_command": scripts.get("aws_cli_command", ""),
                "rollback_command": scripts.get("rollback_command", ""),
                "eventbridge_rule": scripts.get("eventbridge_rule", ""),
                "executed_by": "chatbot",
                "executed_at": None,      # NOT executed — scripts only
                "realized_saving": None,
                "status": "GENERATED_VIA_CHAT",
            })
        except Exception as e:
            print(f"[ChatbotScriptService] Warning: Could not save to SQLite: {e}")

        # Step 8: Build the chat response
        action = recommendation.get("action", "Optimization")
        saving = recommendation.get("estimated_monthly_saving", 0.0)
        tf = scripts.get("terraform_hcl", "")
        cli = scripts.get("aws_cli_command", "")
        rollback = scripts.get("rollback_command", "")

        chat_message = (
            f"✅ **Scripts generated for {resource_name}** (governance APPROVED)\n\n"
            f"**Action:** {action}\n"
            f"**Estimated saving:** ${saving:.2f}/month\n\n"
            f"---\n\n"
            f"**Terraform HCL:**\n```hcl\n{tf}\n```\n\n"
            f"**AWS CLI:**\n```bash\n{cli}\n```\n\n"
            f"**Rollback:**\n```bash\n{rollback}\n```\n\n"
            f"---\n"
            f"> ⚠️ **These scripts are for review only.** "
            f"To execute, go to the **Recommendations tab** in the dashboard, "
            f"find **{resource_name}**, and click **Execute**. "
            f"You must tick the confirmation checkbox and enter your PIN before anything runs."
        )

        return {
            "status": "APPROVED",
            "resource_name": resource_name,
            "action": action,
            "saving_monthly": saving,
            "scripts": scripts,
            "chat_message": chat_message,
        }

    def _find_instance(self, search_term: str) -> Optional[dict]:
        """Find instance by name (partial) or resource_id in parquet."""
        if not os.path.exists(PARQUET_PATH):
            return None
        try:
            df = pd.read_parquet(PARQUET_PATH)
            search_lower = search_term.strip().lower()
            mask = (
                df["resource_name"].str.lower().str.contains(search_lower, na=False) |
                (df["resource_id"].str.lower() == search_lower) |
                df["resource_name"].str.lower().apply(lambda x: isinstance(x, str) and len(x) > 3 and x in search_lower)
            )
            matches = df[mask]
            if matches.empty:
                return None
            # Pick highest-cost match (most likely the one they mean)
            row = matches.loc[matches["total_cost_90d"].fillna(0).idxmax()]
            return row.to_dict()
        except Exception as e:
            print(f"[ChatbotScriptService] Error finding instance: {e}")
            return None

    def _get_recommendation(self, resource_id: str, instance: dict) -> Optional[dict]:
        """Get existing recommendation from SQLite or build a minimal one."""
        # Try existing recommendation first
        existing = self.store._fetchone(
            "SELECT * FROM recommendations WHERE resource_id = ? AND status != 'REMEDIATED' ORDER BY created_at DESC LIMIT 1",
            (resource_id,)
        )
        if existing:
            return existing

        # Build a minimal recommendation from instance data if no existing one
        monthly_cost = float(instance.get("monthly_cost_est", 0) or 0)
        instance_type = str(instance.get("instance_type", ""))
        is_spot_eligible = bool(instance.get("is_spot_eligible", False))

        if monthly_cost <= 0:
            return None

        if is_spot_eligible:
            return {
                "id": f"chat-{resource_id}-spot",
                "resource_id": resource_id,
                "resource_name": str(instance.get("resource_name", "")),
                "instance_type": instance_type,
                "region": str(instance.get("region", "ap-south-1")),
                "track": "spot",
                "action": f"Convert {instance_type} from OnDemand to Spot",
                "current_monthly_cost": monthly_cost,
                "estimated_monthly_saving": round(monthly_cost * 0.65, 2),
                "saving_pct": 65.0,
                "confidence": 0.80,
                "rationale": "Spot-eligible OnDemand instance. 65% cost reduction available.",
                "status": "APPROVED",
            }

        return None
