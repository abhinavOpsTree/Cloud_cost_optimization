"""
core/base_skill.py
------------------
Abstract base classes for all Cloud-Sentry AI skills.

Rules:
- Only components that use Gemini API are called "Agents"
- Skills live inside agents and follow this interface
- Three skill types: Analysis, Governance, Context
- New skills can be added in 15-30 minutes by copying template_skill.py
"""
from abc import ABC, abstractmethod


class BaseAnalysisSkill(ABC):
    """
    Base class for all FinOps Analyst Agent skills.

    Skills in:  skills/analysis/
    Examples:   RightsizingSkill, SpotConversionSkill,
                SchedulePolicySkill, EKSDiagnosisSkill

    Workflow per instance:
        1. can_apply()  → decide if this skill is relevant
        2. analyse()    → inspect the data, produce findings
        3. recommend()  → convert findings into a recommendation dict
        4. generate_script() → produce the runnable scripts
    """

    @abstractmethod
    def can_apply(self, instance: dict) -> bool:
        """
        Return True if this skill should run for the given instance.

        Args:
            instance: A dict row from enriched_instances.parquet

        Returns:
            True  → run analyse() on this instance
            False → skip (skill is not relevant for this instance)

        Example:
            return instance.get("has_performance_data") == True
        """
        pass

    @abstractmethod
    def analyse(self, instance: dict) -> dict:
        """
        Analyse the instance data and return findings.

        Args:
            instance: A dict row from enriched_instances.parquet

        Returns:
            A dict describing what was found.
            Return {} (empty dict) if no actionable finding.

        Example:
            return {
                "signal": "OVER_PROVISIONED",
                "cpu_avg": 2.5,
                "recommended_type": "t3.small"
            }
        """
        pass

    @abstractmethod
    def recommend(self, instance: dict, finding: dict) -> dict | None:
        """
        Convert a finding into a recommendation.

        Args:
            instance: A dict row from enriched_instances.parquet
            finding:  The dict returned by analyse()

        Returns:
            A recommendation dict (see schema below), or None if no action needed.

        Recommendation schema:
            {
                "track": str,                    # "rightsizing"|"spot"|"schedule"|"eks"
                "action": str,                   # human-readable description
                "current_monthly_cost": float,
                "estimated_monthly_saving": float,
                "saving_pct": float,
                "confidence": float,             # 0.0 to 1.0
                "rationale": str,                # visible to engineer
                "has_performance_data": bool,
                "skill_name": str
            }
        """
        pass

    @abstractmethod
    def generate_script(self, instance: dict, recommendation: dict) -> dict:
        """
        Generate executable scripts for the recommendation.

        Args:
            instance:       A dict row from enriched_instances.parquet
            recommendation: The dict returned by recommend()

        Returns:
            {
                "terraform_hcl": str,       # complete Terraform code
                "aws_cli_command": str,     # complete AWS CLI command
                "rollback_command": str,    # complete rollback command
                "eventbridge_rule": str     # EventBridge JSON (schedule track only)
            }
        """
        pass


class BaseGovernanceSkill(ABC):
    """
    Base class for all Governance Agent skills.

    Skills in:  skills/governance/
    Examples:   ProductionShieldSkill (Tier 1),
                RiskFlaggingSkill (Tier 2),
                AmbiguousReasoningSkill (Tier 3 — uses Gemini)

    The governance agent evaluates skills in tier order (1 → 2 → 3).
    The first skill that returns a non-None result wins.
    Tier 1 and 2 are pure Python. Tier 3 calls Gemini.
    Tier 3 CANNOT override Tier 1 or Tier 2 decisions.
    """

    @abstractmethod
    def evaluate(self, instance: dict, recommendation: dict) -> dict | None:
        """
        Evaluate whether the recommendation is safe to execute.

        Args:
            instance:       A dict row from enriched_instances.parquet
            recommendation: A recommendation dict from the recommendations table

        Returns:
            A decision dict if a verdict is reached, or None to pass to next tier.

            Decision schema:
            {
                "status": str,   # "BLOCKED" | "FLAGGED" | "APPROVED"
                "tier": int,     # 1, 2, or 3
                "reason": str    # explanation logged to SQLite and shown in UI
            }

        Rules:
            - Return None to pass the instance to the next governance tier
            - Return a dict to stop evaluation at this tier
            - BLOCKED is permanent and cannot be overridden by higher tiers
            - FLAGGED requires human review before Execute button appears
            - APPROVED allows Execute button to appear immediately
        """
        pass


class BaseContextSkill(ABC):
    """
    Base class for all FinOps Chat Agent context skills.

    Skills in:  skills/context/
    Examples:   EC2FleetContextSkill, NATGatewayContextSkill, SavingsContextSkill

    Context skills load relevant data at session start and inject it
    into the chat agent's system prompt. This grounds the chatbot in
    real OpsTree fleet data and prevents hallucination.
    """

    @abstractmethod
    def load_context(self, instances: list) -> str:
        """
        Load and format context data for injection into the chat system prompt.

        Args:
            instances: List of instance dicts from enriched_instances.parquet

        Returns:
            A formatted string to be injected into the Gemini system prompt.
            Keep it concise — this is part of the token budget.

        Example:
            return f"TOP COST INSTANCE: {name} at ${cost}/month"
        """
        pass
