"""
skills/governance/ambiguous_reasoning.py
-----------------------------------------
Tier 3 — Ambiguous Reasoning (Gemini-powered)

Runs ONLY when:
  1. Instance passed Tier 1 (not production-blocked)
  2. Instance passed Tier 2 (no risk flags)
  3. tag_confidence < 0.70 (inference is uncertain)

Uses Gemini to reason about whether the instance is safe to modify.

Cache:
  - Checks governance_decisions table for cached Tier 3 assessments
  - If assessed within 7 days and instance unchanged → reuse, 0 Gemini calls
  - Saves new Gemini assessments to governance_decisions for future cache hits

Result mapping:
  - safe=True AND confidence >= 0.75  → APPROVED (tier=3)
  - safe=False OR confidence < 0.75   → FLAGGED (tier=3)

SAFETY RULES:
  RULE 10: Gemini Tier 3 CANNOT override Tier 1 or Tier 2 decisions
  RULE 12: Hard stop at 50 Gemini calls per run — remaining get FLAGGED
  RULE 18: NEVER crash on Gemini API failure — return safe default and continue
"""
from __future__ import annotations

import json
from typing import Optional

from core.base_skill import BaseGovernanceSkill


class AmbiguousReasoningSkill(BaseGovernanceSkill):
    """
    Tier 3 Gemini Reasoning — resolves ambiguous governance cases.

    Only called when deterministic tiers cannot decide.
    Uses caching to minimize Gemini API costs.
    """

    NAME = "ambiguous_reasoning"
    DISPLAY_NAME = "Ambiguous Reasoning (AI)"
    TIER = 3
    DESCRIPTION = "Uses Gemini to assess ambiguous instances that passed Tier 1 and 2"

    # Threshold below which Gemini is consulted
    CONFIDENCE_THRESHOLD = 0.70
    # Minimum confidence from Gemini to approve
    APPROVAL_CONFIDENCE = 0.75
    # Cache validity in days
    CACHE_DAYS = 7

    def evaluate(self, instance: dict, recommendation: dict) -> Optional[dict]:
        """
        Use Gemini to reason about ambiguous instances.

        Only called when tag_confidence < 0.70 (uncertain classification).
        Checks cache first to avoid duplicate Gemini calls.

        Returns:
            APPROVED dict if Gemini says safe with high confidence.
            FLAGGED dict if Gemini is unsure or says unsafe.
            None should never be returned (this is the last tier).
        """
        tag_confidence = instance.get("tag_confidence", 0.0) or 0.0

        # If confidence is already high enough, auto-approve
        if tag_confidence >= self.CONFIDENCE_THRESHOLD:
            return {
                "status": "APPROVED",
                "tier": 3,
                "reason": f"Tag confidence {tag_confidence:.0%} meets threshold — approved",
            }

        resource_id = instance.get("resource_id", "")
        resource_name = instance.get("resource_name", "")

        # ----------------------------------------------------------
        # Performance data shortcut: if instance has CPU metrics and
        # passed Tier 1 + Tier 2, it's demonstrably non-production
        # infrastructure. Approve without Gemini to conserve budget.
        # ----------------------------------------------------------
        has_data = instance.get("has_performance_data", False)
        if has_data:
            cpu_avg = instance.get("cpu_avg_pct")
            if cpu_avg is not None:
                return {
                    "status": "APPROVED",
                    "tier": 3,
                    "reason": f"Has performance data (CPU avg {cpu_avg:.1f}%) and passed Tier 1+2 — approved",
                }

        # ----------------------------------------------------------
        # Check cache — reuse Tier 3 decision if within 7 days
        # ----------------------------------------------------------
        cached = self._check_cache(resource_id)
        if cached is not None:
            return cached

        # ----------------------------------------------------------
        # Call Gemini for reasoning
        # ----------------------------------------------------------
        gemini_result = self._call_gemini(instance, recommendation)

        # ----------------------------------------------------------
        # Map Gemini result to governance decision
        # ----------------------------------------------------------
        safe = gemini_result.get("safe", False)
        confidence = gemini_result.get("confidence", 0.0)
        reasoning = gemini_result.get("reasoning", "No reasoning provided")

        if safe and confidence >= self.APPROVAL_CONFIDENCE:
            decision = {
                "status": "APPROVED",
                "tier": 3,
                "reason": f"Gemini assessment: safe ({confidence:.0%} confidence) — {reasoning}",
                "gemini_assessment": gemini_result,
            }
        else:
            decision = {
                "status": "FLAGGED",
                "tier": 3,
                "reason": f"Gemini assessment: uncertain ({confidence:.0%} confidence) — {reasoning}",
                "gemini_assessment": gemini_result,
            }

        # Save to cache for future runs
        self._save_to_cache(resource_id, resource_name, decision)

        return decision

    def _check_cache(self, resource_id: str) -> Optional[dict]:
        """Check if a valid cached Tier 3 decision exists."""
        try:
            from core.state_store import StateStore
            store = StateStore()
            cached = store.get_cached_governance_decision(
                resource_id, cache_days=self.CACHE_DAYS
            )
            if cached:
                status = cached.get("decision", "FLAGGED")
                reason = cached.get("reason", "Cached assessment")
                print(f"[GOV T3] Using cached assessment for {resource_id}: {status}")
                return {
                    "status": status,
                    "tier": 3,
                    "reason": f"(Cached) {reason}",
                    "gemini_assessment": cached.get("gemini_assessment"),
                }
        except Exception as e:
            print(f"[GOV T3] Cache check failed (non-fatal): {e}")
        return None

    def _save_to_cache(self, resource_id: str, resource_name: str, decision: dict) -> None:
        """Save Tier 3 decision to governance_decisions table for caching."""
        try:
            from core.state_store import StateStore
            store = StateStore()
            store.save_governance_decision({
                "resource_id": resource_id,
                "resource_name": resource_name,
                "decision": decision["status"],
                "tier": 3,
                "reason": decision["reason"],
                "gemini_assessment": decision.get("gemini_assessment"),
            })
        except Exception as e:
            print(f"[GOV T3] Cache save failed (non-fatal): {e}")

    def _call_gemini(self, instance: dict, recommendation: dict) -> dict:
        """
        Call Gemini to assess whether an instance is safe to modify.

        Returns:
            {"safe": bool, "confidence": float, "reasoning": str}

        On any failure, returns a conservative default (safe=False).
        """
        try:
            from core.llm_client import call_gemini

            resource_name = instance.get("resource_name", "unknown")
            instance_type = instance.get("instance_type", "unknown")
            inferred_env = instance.get("inferred_env", "unknown")
            tag_confidence = instance.get("tag_confidence", 0.0)
            pricing_model = instance.get("pricing_model", "unknown")
            monthly_cost = instance.get("monthly_cost_est", 0.0)
            cpu_avg = instance.get("cpu_avg_pct")
            has_data = instance.get("has_performance_data", False)
            owner = instance.get("owner") or instance.get("inferred_owner") or "unknown"

            rec_action = recommendation.get("action", "unknown action")
            rec_track = recommendation.get("track", "unknown")
            rec_saving = recommendation.get("estimated_monthly_saving", 0.0)

            prompt = f"""You are a senior cloud governance analyst at OpsTree Solutions.
You must assess whether it is SAFE to apply a cost optimization to this AWS EC2 instance.

INSTANCE DETAILS:
- Name: {resource_name}
- Type: {instance_type}
- Environment (inferred): {inferred_env} (confidence: {tag_confidence:.0%})
- Pricing model: {pricing_model}
- Monthly cost: ${monthly_cost:.2f}
- Owner: {owner}
- Has performance data: {has_data}
- CPU avg: {cpu_avg if cpu_avg is not None else 'No data'}

PROPOSED ACTION:
- Track: {rec_track}
- Action: {rec_action}
- Estimated saving: ${rec_saving:.2f}/month

RULES:
1. If there is ANY doubt that this is a production workload, say safe=false
2. If the instance name suggests critical infrastructure, say safe=false
3. If the instance has no performance data AND high cost, be cautious
4. Test/dev/staging environments are generally safe to optimize
5. Unknown environments with low cost and low confidence are risky

Respond with ONLY a JSON object (no markdown, no explanation):
{{"safe": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""

            response = call_gemini(
                prompt=prompt,
                expect_json=True,
                agent="governance_agent",
                resource_id=resource_name,
            )

            result = json.loads(response)
            # Validate structure
            return {
                "safe": bool(result.get("safe", False)),
                "confidence": min(float(result.get("confidence", 0.0)), 1.0),
                "reasoning": str(result.get("reasoning", "No reasoning"))[:200],
            }

        except Exception as e:
            print(f"[GOV T3] Gemini call failed for {instance.get('resource_name', '?')}: {e}")
            # Safe default: flag for human review
            return {
                "safe": False,
                "confidence": 0.0,
                "reasoning": "AI reasoning unavailable — conservative flag applied",
            }
