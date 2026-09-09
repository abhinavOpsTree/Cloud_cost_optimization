"""
core/models.py
--------------
Pydantic data models for Cloud-Sentry AI.

All models use Python 3.11+ type hints.
Optional fields default to None to support partial data
(e.g. 261 instances have no CPU metrics — those fields are None/NaN).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Verified data constants — hard-coded, never change these
# ---------------------------------------------------------------------------

ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID", "")
ACCOUNT_NAME = "opstree"
TOTAL_ROWS = 16743
UNIQUE_EC2 = 279
TOTAL_COST_90D = 1005.60
EC2_COST_90D = 583.25
NAT_COST_90D = 356.89
DT_COST_90D = 65.39
MONTHLY_RUN_RATE = 335.20
EC2_MONTHLY = 194.42
NAT_MONTHLY = 118.96
DT_MONTHLY = 21.80
INSTANCES_WITH_CPU_DATA = 18
INSTANCES_WITHOUT_CPU_DATA = 261
HARD_BLOCKED_COUNT = 2
EKS_NODE_COUNT = 61
SPOT_ELIGIBLE_COUNT = 94
SPOT_SAVING_MONTHLY = 73.36
PILOT_START = "18 Feb 2026"
PILOT_END = "19 May 2026"
PILOT_DAYS = 89
PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.1-flash"

# ---------------------------------------------------------------------------
# Top 10 instances by 90-day cost (used in chat context and dashboard)
# ---------------------------------------------------------------------------

TOP_10_INSTANCES = [
    {"name": "opstree-open-vpn-server - do no delete", "type": "t3.medium",  "pricing": "OnDemand", "cost_90d": 87.54,  "status": "HARD_BLOCK"},
    {"name": "rhel8",                                   "type": "m5.xlarge",  "pricing": "OnDemand", "cost_90d": 54.83,  "status": "no env tag"},
    {"name": "perfeasy-bp-main",                        "type": "c5.2xlarge", "pricing": "OnDemand", "cost_90d": 52.72,  "status": "OPTIMIZED"},
    {"name": "bp-testing-windows",                      "type": "t3.xlarge",  "pricing": "OnDemand", "cost_90d": 47.84,  "status": "test env"},
    {"name": "bp-main",                                 "type": "c5a.2xlarge","pricing": "OnDemand", "cost_90d": 35.71,  "status": "no env tag"},
    {"name": "s3-support-amd",                          "type": "c5.2xlarge", "pricing": "OnDemand", "cost_90d": 32.83,  "status": "no env tag"},
    {"name": "bp-main-amd-agent",                       "type": "t2.xlarge",  "pricing": "OnDemand", "cost_90d": 31.77,  "status": "OVER_PROVISIONED"},
    {"name": "ot-mumbai-v1-35-standard-nodes-Node",     "type": "t3.medium",  "pricing": "OnDemand", "cost_90d": 30.78,  "status": "EKS NODE"},
    {"name": "ecr-proxy - do not delete",               "type": "t2.micro",   "pricing": "OnDemand", "cost_90d": 26.16,  "status": "HARD_BLOCK"},
    {"name": "ot-mumbai-v1-34-standard-nodes-Node",     "type": "t3.medium",  "pricing": "OnDemand", "cost_90d": 28.16,  "status": "EKS NODE"},
]

# ---------------------------------------------------------------------------
# NAT Gateway breakdown (verified from billing export)
# ---------------------------------------------------------------------------

NAT_GATEWAY_DATA = [
    {"name": "eksctl-performance-test-cluster/NAT", "cost_90d": 89.71, "monthly": 29.90, "region": "ap-south-1"},
    {"name": "kubelift-test-cluster",               "cost_90d": 67.69, "monthly": 22.56, "region": "us-west-2", "note": "possibly orphaned"},
    {"name": "ot-mumbai-v1-33 cluster NAT",         "cost_90d": 35.39, "monthly": 11.80, "region": "ap-south-1"},
    {"name": "ot-mumbai-v1-34 cluster NAT",         "cost_90d": 35.00, "monthly": 11.67, "region": "ap-south-1"},
    {"name": "ot-mumbai-v1-35 cluster NAT",         "cost_90d": 34.78, "monthly": 11.59, "region": "ap-south-1"},
    {"name": "eks-upgrade-lab NAT",                 "cost_90d": 16.01, "monthly":  5.34, "region": "us-east-1"},
]

# ---------------------------------------------------------------------------
# EKS cluster data (verified from billing export)
# ---------------------------------------------------------------------------

EKS_CLUSTER_DATA = [
    {"cluster": "ot-mumbai-v1-35",      "nodes": 16, "cost_90d": 30.78, "monthly": 10.26},
    {"cluster": "ot-mumbai-v1-34",      "nodes": 13, "cost_90d": 28.16, "monthly":  9.39},
    {"cluster": "ot-mumbai-v1-33",      "nodes": 10, "cost_90d": 20.25, "monthly":  6.75},
    {"cluster": "bp-on-k8s",            "nodes":  4, "cost_90d": 17.59, "monthly":  5.86},
    {"cluster": "unknown-cluster",      "nodes":  6, "cost_90d": 12.13, "monthly":  4.04},
    {"cluster": "kubelift-test-cluster","nodes": 12, "cost_90d":  5.18, "monthly":  1.73},
]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EnrichedInstance(BaseModel):
    """One row from enriched_instances.parquet — one unique EC2 instance."""

    resource_id: str
    resource_name: str = ""
    instance_type: str = ""
    pricing_model: str = ""                # "OnDemand" or "Spot"
    region: str = ""
    environment: Optional[str] = None      # from billing export (sparse)
    owner: Optional[str] = None
    team: Optional[str] = None
    all_tags: Optional[Dict[str, Any]] = None   # parsed JSON dict

    # Performance metrics — NaN/None for 261 instances without CloudWatch data
    cpu_avg_pct: Optional[float] = None    # NEVER show 0% for None — show "No metrics"
    cpu_max_pct: Optional[float] = None
    cpu_p95_pct: Optional[float] = None
    net_in_mbps: Optional[float] = None
    net_out_mbps: Optional[float] = None

    rightsizing_signal: Optional[str] = None   # "OVER_PROVISIONED" | "SEVERELY_OVER" | "OPTIMIZED" | None

    # Cost
    total_cost_90d: float = 0.0
    monthly_cost_est: float = 0.0          # total_cost_90d / 89 * 30

    # Inference results from 5-layer tag inference
    inferred_env: str = "unknown"          # "production"|"staging"|"test"|"dev"|"unknown"
    inferred_owner: Optional[str] = None
    inferred_workload: str = "UNKNOWN"     # "EKS_NODE"|"NETWORK_GATEWAY"|"WEB_SERVER"|"BATCH"|"UNKNOWN"
    safety_tier: str = "APPROVE"           # "HARD_BLOCK"|"FLAG"|"APPROVE"
    tag_confidence: float = 0.0            # 0.0 to 1.0
    tag_source: str = "unknown"            # "explicit"|"name_pattern"|"eks_pattern"|"type_heuristic"|"llm"

    # Computed flags
    is_spot_eligible: bool = False
    cluster_name: Optional[str] = None    # EKS cluster name if EKS node
    has_performance_data: bool = False    # True if cpu_avg_pct is not None/NaN


class Recommendation(BaseModel):
    """A single recommendation generated by the FinOps Analyst Agent."""

    id: str                                # uuid4
    resource_id: str
    resource_name: str = ""
    instance_type: str = ""
    region: str = ""
    track: str                             # "rightsizing"|"spot"|"schedule"|"eks"|"tagging"
    action: str                            # human-readable description
    current_monthly_cost: float = 0.0
    estimated_monthly_saving: float = 0.0
    saving_pct: float = 0.0
    confidence: float = 0.0               # 0.0 to 1.0
    rationale: str = ""                   # explanation visible to engineer
    status: str = "PENDING_REVIEW"        # PENDING_REVIEW|APPROVED|FLAGGED|BLOCKED|EXECUTING|REMEDIATED|FAILED
    gate_tier: Optional[int] = None       # 1, 2, or 3
    gate_reason: Optional[str] = None
    has_performance_data: bool = False
    skill_name: str = ""
    created_at: str = ""
    executed_at: Optional[str] = None


class RemediationRecord(BaseModel):
    """A record of an executed or generated remediation script."""

    id: str                                # uuid4
    recommendation_id: str
    resource_id: str
    resource_name: str = ""
    action_taken: str = ""
    terraform_hcl: str = ""
    aws_cli_command: str = ""
    rollback_command: str = ""
    eventbridge_rule: Optional[str] = None
    executed_by: str = "engineer"          # always human
    executed_at: Optional[str] = None     # filled when engineer confirms
    realized_saving: Optional[float] = None
    status: str = "GENERATED"             # GENERATED|EXECUTED|ROLLED_BACK|FAILED


class ConversationMessage(BaseModel):
    """A single message in a FinOps Chat Agent session."""

    id: Optional[int] = None
    session_id: str
    role: str                              # "user" or "assistant"
    message: str
    timestamp: str
    resource_mentioned: Optional[str] = None   # instance name if engineer asked about one


class GovernanceDecision(BaseModel):
    """A governance evaluation result stored for audit and caching."""

    id: Optional[int] = None
    resource_id: str
    resource_name: str = ""
    decision: str                          # "BLOCKED"|"FLAGGED"|"APPROVED"
    tier: Optional[int] = None            # 1, 2, or 3
    reason: str = ""
    gemini_assessment: Optional[str] = None   # JSON string, Tier 3 only
    assessed_at: str = ""
    human_override: bool = False
    human_override_reason: Optional[str] = None
    run_id: Optional[str] = None


class LLMUsage(BaseModel):
    """Tracks every Gemini API call for cost control."""

    id: Optional[int] = None
    run_id: Optional[str] = None
    agent: str                             # which agent made the call
    resource_id: Optional[str] = None
    model: str = PRIMARY_MODEL
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0       # approximate (word count based)
    called_at: str = ""


class IngestRun(BaseModel):
    """Records each Fleet Intelligence Processor run."""

    id: Optional[int] = None
    run_id: str
    source_file: str
    source_file_size: int = 0
    instances_found: int = 0
    eks_nodes_found: int = 0
    hard_blocked_found: int = 0
    spot_eligible_found: int = 0
    gemini_calls_used: int = 0
    started_at: str = ""
    completed_at: str = ""
    status: str = "COMPLETED"             # COMPLETED|FAILED


class AnalysisRun(BaseModel):
    """Records a complete analysis run (Analyst + Governance)."""

    run_id: str
    started_at: str = ""
    completed_at: str = ""
    instances_analysed: int = 0
    recommendations_generated: int = 0
    blocked_count: int = 0
    flagged_count: int = 0
    approved_count: int = 0
    gemini_calls_total: int = 0
    estimated_gemini_cost_usd: float = 0.0
    fleet_summary: Optional[str] = None   # Gemini-generated paragraph
    status: str = "COMPLETED"
