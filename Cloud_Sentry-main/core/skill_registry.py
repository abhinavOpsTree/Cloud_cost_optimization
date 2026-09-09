"""
core/skill_registry.py
-----------------------
Central registry for all Cloud-Sentry AI skills.

Imports and registers all skills by type:
  ANALYSIS_SKILLS    — RightsizingSkill, SpotConversionSkill, SchedulePolicySkill, EKSDiagnosisSkill
  GOVERNANCE_SKILLS  — ProductionShieldSkill, RiskFlaggingSkill, AmbiguousReasoningSkill
  REMEDIATION_SKILLS — TerraformWriterSkill, AWSCLIWriterSkill, RollbackGeneratorSkill, EventBridgeWriterSkill
  CONTEXT_SKILLS     — EC2FleetContextSkill, NATGatewayContextSkill, SavingsContextSkill
"""
from __future__ import annotations

from typing import Dict, List

from skills.analysis.rightsizing import RightsizingSkill
from skills.analysis.spot_conversion import SpotConversionSkill
from skills.analysis.schedule_policy import SchedulePolicySkill
from skills.analysis.eks_diagnosis import EKSDiagnosisSkill
from skills.governance.production_shield import ProductionShieldSkill
from skills.governance.risk_flagging import RiskFlaggingSkill
from skills.governance.ambiguous_reasoning import AmbiguousReasoningSkill
from skills.remediation.terraform_writer import TerraformWriterSkill
from skills.remediation.aws_cli_writer import AWSCLIWriterSkill
from skills.remediation.rollback_generator import RollbackGeneratorSkill
from skills.remediation.eventbridge_writer import EventBridgeWriterSkill
from skills.context.ec2_fleet_context import EC2FleetContextSkill
from skills.context.nat_gateway_context import NATGatewayContextSkill
from skills.context.savings_context import SavingsContextSkill

ANALYSIS_SKILLS = [RightsizingSkill(), SpotConversionSkill(),
                   SchedulePolicySkill(), EKSDiagnosisSkill()]
GOVERNANCE_SKILLS = [ProductionShieldSkill(), RiskFlaggingSkill(),
                     AmbiguousReasoningSkill()]
REMEDIATION_SKILLS = [TerraformWriterSkill(), AWSCLIWriterSkill(),
                      RollbackGeneratorSkill(), EventBridgeWriterSkill()]
CONTEXT_SKILLS = [EC2FleetContextSkill(), NATGatewayContextSkill(),
                  SavingsContextSkill()]


class SkillRegistry:
    """Central registry for all skills in the system."""

    def __init__(self):
        self._analysis_skills = []
        self._governance_skills = []
        self._context_skills = []
        self._remediation_skills = []

    def register_defaults(self) -> None:
        """Register all built-in skills."""
        self._analysis_skills = [
            {"name": s.NAME, "display_name": s.DISPLAY_NAME,
             "description": s.DESCRIPTION, "class": type(s),
             "instance": s, "uses_ai": False, "track": s.TRACK}
            for s in ANALYSIS_SKILLS
        ]
        self._governance_skills = [
            {"name": s.NAME, "display_name": s.DISPLAY_NAME,
             "tier": s.TIER, "description": s.DESCRIPTION,
             "class": type(s), "instance": s,
             "uses_ai": s.NAME == "ambiguous_reasoning"}
            for s in GOVERNANCE_SKILLS
        ]
        self._remediation_skills = [
            {"name": s.NAME, "display_name": s.DISPLAY_NAME,
             "class": type(s), "instance": s, "uses_ai": False}
            for s in REMEDIATION_SKILLS
        ]
        self._context_skills = [
            {"name": s.NAME, "display_name": s.DISPLAY_NAME,
             "class": type(s), "instance": s, "uses_ai": False}
            for s in CONTEXT_SKILLS
        ]

    def get_governance_skills(self) -> List[dict]:
        return sorted(self._governance_skills, key=lambda s: s.get("tier", 99))

    def get_analysis_skills(self) -> List[dict]:
        return self._analysis_skills

    def get_context_skills(self) -> List[dict]:
        return self._context_skills

    def get_remediation_skills(self) -> List[dict]:
        return self._remediation_skills

    def get_all_skills_summary(self) -> dict:
        all_skills = (
            self._analysis_skills + self._governance_skills
            + self._context_skills + self._remediation_skills
        )
        return {
            "total": len(all_skills),
            "analysis": len(self._analysis_skills),
            "governance": len(self._governance_skills),
            "context": len(self._context_skills),
            "remediation": len(self._remediation_skills),
            "skills": [
                {"name": s.get("name"), "display_name": s.get("display_name"),
                 "description": s.get("description", ""), "uses_ai": s.get("uses_ai", False)}
                for s in all_skills
            ],
        }
