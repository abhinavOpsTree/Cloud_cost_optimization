"""
skills/governance/production_shield.py
---------------------------------------
Tier 1 — Production Shield (Hard Block)

This is the FIRST governance check. It runs BEFORE Tier 2 and Tier 3.
If this skill returns a result, the instance is PERMANENTLY blocked.
No UI override exists. No higher tier can reverse this.

Pure Python — zero Gemini calls.

Conditions that trigger HARD_BLOCK:
  1. resource_name contains "do no delete"  (typo variant in pilot data)
  2. resource_name contains "do not delete" (correct spelling)
  3. env/environment/Environment tag == "production" or "prod"
  4. inferred_env == "production" with high-confidence source (explicit/eks_pattern)

Pilot instances caught:
  - opstree-open-vpn-server - do no delete  → Condition 1
  - ecr-proxy - do not delete               → Condition 2 (also has Production tag)

SAFETY RULES (from spec — absolute, no exceptions):
  RULE 2:  NEVER touch production-tagged instance under any circumstance
  RULE 3:  NEVER touch "do not delete" OR "do no delete" instance (both variants)
  RULE 9:  HARD_BLOCK is permanent — no UI override button exists
  RULE 13: BLOCKED instances: NO buttons at all — not greyed, completely absent from DOM
"""
from __future__ import annotations

import json
from typing import Optional

from core.base_skill import BaseGovernanceSkill


class ProductionShieldSkill(BaseGovernanceSkill):
    """
    Tier 1 Hard Block — protects production infrastructure.

    This skill MUST be evaluated first. Its decisions are final and permanent.
    """

    NAME = "production_shield"
    DISPLAY_NAME = "Production Shield"
    TIER = 1
    DESCRIPTION = "Hard-blocks production instances and protected resources"

    def evaluate(self, instance: dict, recommendation: dict) -> Optional[dict]:
        """
        Check if this instance must be permanently blocked.

        Returns a BLOCKED decision dict, or None to pass to Tier 2.

        The order of checks matters:
          1. Name pattern "do no delete" (catches VPN server)
          2. Name pattern "do not delete" (catches ECR proxy)
          3. Explicit production tags in all_tags
          4. High-confidence inferred production environment
        """
        name = str(instance.get("resource_name", "")).lower()
        tags = self._parse_tags(instance.get("all_tags", "{}"))
        track = str(recommendation.get("track", "")).lower()

        # ---------------------------------------------------------------
        # Condition 1 — Name contains "do no delete" (typo variant)
        # Catches: opstree-open-vpn-server - do no delete
        # ---------------------------------------------------------------
        if "do no delete" in name:
            if track in ("termination", "deletion"):
                return {
                    "status": "BLOCKED",
                    "tier": 1,
                    "reason": "Name contains 'do no delete' — Tier 1 hard block against termination",
                }

        # ---------------------------------------------------------------
        # Condition 2 — Name contains "do not delete" (correct spelling)
        # Catches: ecr-proxy - do not delete
        # ---------------------------------------------------------------
        if "do not delete" in name:
            if track in ("termination", "deletion"):
                return {
                    "status": "BLOCKED",
                    "tier": 1,
                    "reason": "Name contains 'do not delete' — Tier 1 hard block against termination",
                }

        # ---------------------------------------------------------------
        # Condition 3 — Explicit production tag in all_tags
        # Check keys: env, environment, Environment
        # Check values: production, prod (case-insensitive)
        # ---------------------------------------------------------------
        for key in ("env", "environment", "Environment"):
            val = str(tags.get(key, "")).strip().lower()
            if val in ("production", "prod"):
                return {
                    "status": "BLOCKED",
                    "tier": 1,
                    "reason": f"Tag {key}='{tags.get(key)}' — production environment hard block",
                }

        # ---------------------------------------------------------------
        # Condition 4 — High-confidence inferred production
        # Only if source is "explicit" or "eks_pattern" (reliable sources)
        # Low-confidence inferences (name_pattern, type_heuristic, llm)
        # go to Tier 3 for Gemini review instead.
        # ---------------------------------------------------------------
        inferred_env = str(instance.get("inferred_env", "")).lower()
        tag_source = str(instance.get("tag_source", ""))
        if inferred_env == "production" and tag_source in ("explicit", "eks_pattern"):
            return {
                "status": "BLOCKED",
                "tier": 1,
                "reason": "Inferred environment = production (high confidence) — hard block",
            }

        # Not blocked by Tier 1 — pass to Tier 2
        return None

    def _parse_tags(self, raw) -> dict:
        """Parse all_tags from string to dict."""
        if not raw or raw == "{}":
            return {}
        try:
            if isinstance(raw, dict):
                return raw
            return json.loads(str(raw))
        except Exception:
            return {}
