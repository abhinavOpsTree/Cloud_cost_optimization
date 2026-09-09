"""
api/main.py
-----------
FastAPI application for Cloud-Sentry AI.

All API routes:
  GET  /api/health                → health check
  POST /api/ingest                → run Fleet Intelligence Processor
  GET  /api/instances             → paginated enriched instances
  POST /api/analyse               → run FinOps Analyst + Governance
  GET  /api/recommendations       → all recommendations (filterable)
  POST /api/execute/{rec_id}      → DevOps Remediation Agent → SSE stream
  GET  /api/stream/{rec_id}       → SSE execution stream
  GET  /api/savings               → savings summary + ROI
  POST /api/chat                  → FinOps Chat Agent → SSE stream
  GET  /api/chat/history          → conversation history
  GET  /api/tag-audit             → run tag compliance reporter
  GET  /api/tag-audit/download    → download CSV
  GET  /api/nat-gateway           → NAT Gateway breakdown
  GET  /api/anomalies             → cost anomalies
  GET  /api/llm-usage             → Gemini API usage stats
  GET  /api/what-if/{resource_id} → Spot what-if simulator
  GET  /api/fleet-summary         → latest AI-generated fleet summary
  GET  /api/skills                → registered skills list
  GET  /api/projection            → 30-day cost projection
"""
from __future__ import annotations

import json
import math
import os
import csv
import math
import os
import sys
import traceback
import uuid
import yaml
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, Request, Response, Header, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from core.admin_auth import is_admin, is_master_admin, get_master_admin
from core.state_store import StateStore
from services.spot_simulator import SpotSimulator
from core.security import PINVerifier
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Cloud-Sentry AI", version="1.0.0-pilot")

@app.on_event("startup")
def startup_event():
    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
        master = config.get("skill_contribution", {}).get("master_admin", "")
        admins = config.get("skill_contribution", {}).get("admins", [])
        store = StateStore()
        store.seed_default_admins(master, admins)
    except Exception as e:
        print(f"Failed to seed default admins: {e}")

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] + allow_credentials=True is forbidden by the CORS spec —
    # browsers silently block ALL responses when both are set together.
    # This API is stateless (no cookies, no cross-origin auth headers needed),
    # so credentials=False is correct and makes the wildcard origin work properly.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitize_nan(val):
    """Convert NaN/Infinity to None for JSON serialization recursively."""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, dict):
        return {k: _sanitize_nan(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_nan(v) for v in val]
    return val

def _sanitize_dict(d: dict) -> dict:
    """Sanitize all NaN values in a dict for JSON."""
    return _sanitize_nan(d)






# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0-pilot",
        "account": "702037529261",
        "account_name": "opstree",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/data-completeness
# ---------------------------------------------------------------------------
@app.get("/api/data-completeness")
async def data_completeness():
    """Return metrics on data availability across the fleet."""
    import os
    import pandas as pd
    
    total = 0
    with_billing = 0
    with_cpu = 0
    
    if os.path.exists("cache/enriched_instances.parquet"):
        try:
            df = pd.read_parquet("cache/enriched_instances.parquet")
            if not df.empty:
                total = len(df)
                if "monthly_cost_est" in df.columns:
                    with_billing = int((df["monthly_cost_est"] > 0).sum())
                if "cpu_avg_pct" in df.columns:
                    with_cpu = int(df["cpu_avg_pct"].notna().sum())
        except Exception:
            pass
            
    return {
        "total_analyzed": total,
        "instances_with_billing_data": with_billing,
        "instances_with_cloudwatch_data": with_cpu,
        "telemetry_coverage_percent": round((with_cpu / total * 100) if total > 0 else 0, 1),
        "billing_coverage_percent": round((with_billing / total * 100) if total > 0 else 0, 1)
    }

def compute_fleet_health() -> dict:
    import os
    import pandas as pd
    from core.state_store import StateStore
    
    ss = StateStore()
    all_recs = ss.get_all_recommendations()
    potential_savings = sum(r.get("estimated_monthly_saving", 0) or 0 for r in all_recs)
    
    telemetry_coverage = 0.0
    total_instances = 0
    blocked_instances = 0
    current_spend = 0.0
    
    if os.path.exists("cache/enriched_instances.parquet"):
        try:
            df = pd.read_parquet("cache/enriched_instances.parquet")
            if not df.empty:
                # Filter to active footprint (Active or Stopped)
                if "lifecycle_state" in df.columns:
                    df = df[df["lifecycle_state"].isin(["Active", "Stopped"])]
                    
                total_instances = len(df)
                if "monthly_cost_est" in df.columns:
                    current_spend += float(df["monthly_cost_est"].sum())
                if "cpu_avg_pct" in df.columns:
                    with_cpu = int(df["cpu_avg_pct"].notna().sum())
                    telemetry_coverage = round((with_cpu / total_instances * 100) if total_instances > 0 else 0, 1)
                if "safety_tier" in df.columns:
                    blocked_instances = int((df["safety_tier"] == "Blocked").sum())
        except Exception:
            pass

    if os.path.exists("cache/nat_gateway_data.parquet"):
        try:
            df_nat = pd.read_parquet("cache/nat_gateway_data.parquet")
            if not df_nat.empty and "monthly_cost" in df_nat.columns:
                current_spend += float(df_nat["monthly_cost"].sum())
        except Exception:
            pass
            
    if current_spend > 0:
        opt_eff = 100.0 - min(100.0, (potential_savings / current_spend) * 100.0)
    else:
        opt_eff = 100.0

    if total_instances > 0:
        gov_comp = ((total_instances - blocked_instances) / total_instances) * 100.0
    else:
        gov_comp = 100.0
        
    fleet_health_score = round(0.45 * opt_eff + 0.30 * telemetry_coverage + 0.25 * gov_comp)
    
    return {
        "score": fleet_health_score,
        "optimization_efficiency": round(opt_eff, 1),
        "telemetry_coverage": round(telemetry_coverage, 1),
        "governance_compliance": round(gov_comp, 1)
    }

# ---------------------------------------------------------------------------
# GET /api/time-series-stats
# ---------------------------------------------------------------------------
@app.get("/api/time-series-stats")
def time_series_stats(days: int = 90, start_date: str = None, end_date: str = None):
    """Aggregate costs from local parquet (instant) with live API fallback."""
    import os
    import pandas as pd
    try:
        from datetime import timedelta, datetime
        
        if not end_date:
            e_dt = datetime.utcnow()
            end_date_str = e_dt.strftime("%Y-%m-%d")
            display_end = e_dt.strftime("%d %b %Y")
        else:
            end_date_str = end_date
            display_end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d %b %Y")
            
        if not start_date:
            s_dt = datetime.utcnow() - timedelta(days=days)
            start_date_str = s_dt.strftime("%Y-%m-%d")
            display_start = s_dt.strftime("%d %b %Y")
        else:
            start_date_str = start_date
            display_start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d %b %Y")
            s_dt = datetime.strptime(start_date, "%Y-%m-%d")
            e_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
            days = max(1, (e_dt - s_dt).days)

        ec2_spend = 0.0
        active_instances = 0
        regions = set()
        
        # 1. Fetch live EC2 date-ranged spend from UnitEconPro
        try:
            from core.uniteconpro_client import get_ec2_summary
            summary = get_ec2_summary(account="opstree", start_date=start_date_str, end_date=end_date_str)
            if summary:
                ec2_spend = summary.get("total_cost", 0.0)
                active_instances = summary.get("total_instances", 0)
        except Exception as e:
            logger.error(f"Failed to fetch live summary: {e}")

        # 2. Extract active_regions from local parquet snapshot (not date-filtered)
        if os.path.exists("cache/enriched_instances.parquet"):
            try:
                df = pd.read_parquet("cache/enriched_instances.parquet")
                if not df.empty and "region" in df.columns:
                    regions = set(df["region"].dropna().unique())
            except Exception:
                pass

        nat_spend = 0.0
        if os.path.exists("cache/nat_gateway_data.parquet"):
            df_nat = pd.read_parquet("cache/nat_gateway_data.parquet")
            if not df_nat.empty and "cost_90d" in df_nat.columns:
                nat_spend = round(float(df_nat["cost_90d"].sum()), 2)
            
        total_spend = ec2_spend + nat_spend
        
        return {
            "days": days,
            "start_date": display_start,
            "end_date": display_end,
            "total_spend": round(total_spend, 2),
            "nat_gateway_spend": round(nat_spend, 2),
            "active_instances": active_instances,
            "active_regions": max(1, len(regions))
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Global Analysis Progress
# ---------------------------------------------------------------------------
import threading as _threading

ANALYSIS_PROGRESS = {"current": 0, "total": 0, "status": "idle"}
_progress_lock = _threading.Lock()

@app.get("/api/analyse/progress")
async def get_analyse_progress():
    with _progress_lock:
        return {**ANALYSIS_PROGRESS}

# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------
@app.post("/api/ingest")
def ingest(days: int = 90, start_date: str = None, end_date: str = None):
    """Run Fleet Intelligence Processor. Returns summary stats."""
    try:
        from agents.fleet_intelligence_processor import FleetIntelligenceProcessor
        from core.state_store import StateStore

        ss = StateStore()
        run_id = ss.start_analysis_run()
        result = FleetIntelligenceProcessor().run(days=days, start_date=start_date, end_date=end_date)
        return _sanitize_dict({**result, "run_id": run_id, "status": "completed"})
    except Exception as e:
        return JSONResponse(
            {"error": str(e), "traceback": traceback.format_exc()},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# GET /api/instances
# ---------------------------------------------------------------------------
@app.get("/api/instances")
async def get_instances(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    region: Optional[str] = None,
    pricing_model: Optional[str] = None,
    safety_tier: Optional[str] = None,
    has_performance_data: Optional[bool] = None,
    search: Optional[str] = None,
):
    """Return enriched instances."""
    import os
    import pandas as pd
    if not os.path.exists("cache/enriched_instances.parquet"):
        return {"instances": [], "total": 0, "page": page, "limit": limit}
    
    df = pd.read_parquet("cache/enriched_instances.parquet")
    all_instances = [_sanitize_dict(row.to_dict()) for _, row in df.iterrows()]

    filtered = []
    for inst in all_instances:
        if region and inst.get("region") != region:
            continue
        if pricing_model and inst.get("pricing_model") != pricing_model:
            continue
        if safety_tier and inst.get("safety_tier") != safety_tier:
            continue
        if has_performance_data is not None and inst.get("has_performance_data") != has_performance_data:
            continue
        if search and search.lower() not in str(inst.get("resource_name", "")).lower():
            continue
        filtered.append(inst)

    total = len(filtered)
    start = (page - 1) * limit
    page_instances = filtered[start:start + limit]

    return {"instances": page_instances, "total": total, "page": page, "limit": limit}


# ---------------------------------------------------------------------------
# POST /api/analyse
# ---------------------------------------------------------------------------
@app.post("/api/analyse")
def analyse():
    """Run FinOps Analyst + Governance Agent. Returns summary."""
    try:
        from agents.finops_analyst_agent import FinOpsAnalystAgent
        from core.state_store import StateStore

        ss = StateStore()
        run_id = ss.start_analysis_run()

        with _progress_lock:
            ANALYSIS_PROGRESS["current"] = 0
            ANALYSIS_PROGRESS["total"] = 0
            ANALYSIS_PROGRESS["status"] = "starting"

        def progress_cb(current, total, status):
            with _progress_lock:
                ANALYSIS_PROGRESS["current"] = current
                ANALYSIS_PROGRESS["total"] = total
                ANALYSIS_PROGRESS["status"] = status

        stats = FinOpsAnalystAgent().run(run_id=run_id, progress_callback=progress_cb)
        
        with _progress_lock:
            ANALYSIS_PROGRESS["status"] = "completed"
        return _sanitize_dict({"run_id": run_id, **stats, "status": "completed"})
    except Exception as e:
        return JSONResponse(
            {"error": str(e), "traceback": traceback.format_exc()},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# GET /api/recommendations
# ---------------------------------------------------------------------------
@app.get("/api/recommendations")
async def get_recommendations(
    status: Optional[str] = None,
    track: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    sort_by: str = "estimated_monthly_saving",
):
    from core.state_store import StateStore
    import pandas as pd
    import math

    ss = StateStore()
    recs = ss.get_all_recommendations(status=status, track=track)
    
    from core.instance_specs import get_instance_specs
    
    for rec in recs:
        rec["current_instance_specs"] = get_instance_specs(
            rec.get("instance_type", "")
        )
        recommended_instance_type = rec.get("recommended_instance_type", "")
        if not recommended_instance_type:
            action = rec.get("action", "")
            if " to " in action:
                parts = action.split(" to ")
                if len(parts) > 1:
                    recommended_instance_type = parts[1].strip()
        rec["recommended_instance_specs"] = get_instance_specs(
            recommended_instance_type
        )
        
        raw_reasons = rec.get("confidence_reasons", "[]")
        try:
            rec["confidence_reasons"] = json.loads(raw_reasons)
        except (json.JSONDecodeError, TypeError):
            rec["confidence_reasons"] = []

    recs.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=True)
    total = len(recs)
    start = (page - 1) * limit
    paginated = recs[start:start + limit]
    
    return {"recommendations": _sanitize_nan(paginated), "total": total}


# ---------------------------------------------------------------------------
# GET /api/recommendations/{rec_id}/script-preview
# ---------------------------------------------------------------------------
@app.get("/api/recommendations/{rec_id}/script-preview")
async def get_script_preview(rec_id: str):
    """Generate read-only script preview for a recommendation without execution."""
    from core.state_store import StateStore
    from skills.remediation.terraform_writer import TerraformWriterSkill
    from skills.remediation.aws_cli_writer import AWSCLIWriterSkill
    from skills.remediation.rollback_generator import RollbackGeneratorSkill

    ss = StateStore()
    rec = ss.get_recommendation(rec_id)
    if not rec:
        return JSONResponse({"error": "Recommendation not found"}, status_code=404)

    # Use the recommendation data as the instance metadata as well, since it has the keys
    tf_writer = TerraformWriterSkill()
    cli_writer = AWSCLIWriterSkill()
    rb_writer = RollbackGeneratorSkill()

    return {
        "terraform_hcl": tf_writer.generate(rec, rec),
        "aws_cli_command": cli_writer.generate(rec, rec),
        "rollback_command": rb_writer.generate(rec, rec)
    }


# ---------------------------------------------------------------------------
# POST /api/execute/{rec_id} — SSE stream
# ---------------------------------------------------------------------------
@app.post("/api/execute/{rec_id}")
async def execute_recommendation(rec_id: str):
    """Trigger DevOps Remediation Agent — returns SSE stream."""
    from core.state_store import StateStore
    from agents.devops_remediation_agent import DevOpsRemediationAgent
    from api.sse import execution_event_generator

    ss = StateStore()
    agent = DevOpsRemediationAgent()
    return StreamingResponse(
        execution_event_generator(rec_id, ss, agent),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
#   POST /api/govern                (Trigger Governance Agent)
#
# Skill Contribution API:
#   POST /api/skill-submissions                 (Submit a new skill)
#   GET /api/skill-submissions                  (List submissions)
#   POST /api/skill-submissions/{id}/approve    (Admin approve)
#   POST /api/skill-submissions/{id}/reject     (Admin reject)
#   GET /api/skill-admins                       (List admins)
#   POST /api/skill-admins                      (Add admin)
#   DELETE /api/skill-admins/{email}            (Remove admin)
# ---------------------------------------------------------------------------
@app.get("/api/stream/{rec_id}")
async def stream_execution(rec_id: str):
    """SSE stream for execution (GET variant for EventSource)."""
    from core.state_store import StateStore
    from agents.devops_remediation_agent import DevOpsRemediationAgent
    from api.sse import execution_event_generator

    ss = StateStore()
    agent = DevOpsRemediationAgent()
    return StreamingResponse(
        execution_event_generator(rec_id, ss, agent),
        media_type="text/event-stream",
    )
# ---------------------------------------------------------------------------
# POST /api/execute/{rec_id}/confirm
# ---------------------------------------------------------------------------
# POST /api/verify-pin
@app.post("/api/verify-pin")
async def verify_pin(request: Request):
    """
    Verify execution PIN before confirming deploy.
    Called by frontend before activating the Confirm and Deploy button.

    Body: {"pin": "1234", "rec_id": "optional-rec-id-for-logging"}
    Returns: {"success": true} or {"success": false, "reason": "...", "message": "..."}
    """
    try:
        body = await request.json()
        pin = str(body.get("pin", ""))
        rec_id = body.get("rec_id", "")
        client_ip = request.client.host if request.client else "unknown"

        if not pin:
            return JSONResponse({"success": False, "reason": "no_pin", "message": "PIN required."}, status_code=400)

        verifier = PINVerifier()
        result = verifier.verify(pin, client_ip=client_ip)

        # Log failed attempts to SQLite
        if not result.get("success"):
            try:
                state_store._execute(
                    "INSERT OR IGNORE INTO recommendations(id) VALUES(?)",  # dummy to ensure DB is open
                    (rec_id,)
                ) if False else None  # don't actually insert
                # Just print for now — a dedicated pin_failures table can be added in Phase 2
                print(f"[PIN] Failed attempt from {client_ip} for rec_id={rec_id}: {result.get('reason')}")
            except Exception:
                pass

        return result
    except Exception as e:
        return JSONResponse({"success": False, "reason": "error", "message": str(e)}, status_code=500)

@app.post("/api/execute/{rec_id}/confirm")
async def confirm_execution(rec_id: str):
    """Confirm execution of a recommendation."""
    from core.state_store import StateStore
    from datetime import datetime

    ss = StateStore()
    
    # Update recommendation status
    ss.mark_recommendation_executed(rec_id)
    
    # Update remediations table
    rec = ss.get_recommendation(rec_id)
    saving = rec.get("estimated_monthly_saving", 0) if rec else 0
    now = datetime.utcnow().isoformat()
    
    ss._execute(
        "UPDATE remediations SET status='EXECUTED', executed_at=?, realized_saving=? WHERE recommendation_id=? AND status='GENERATED'",
        (now, saving, rec_id)
    )
    return {"status": "success"}

# ---------------------------------------------------------------------------
# GET /api/remediations
# ---------------------------------------------------------------------------
@app.get("/api/remediations")
async def get_remediations():
    """Get all executed remediations."""
    from core.state_store import StateStore
    import sqlite3

    ss = StateStore()
    remediations = ss.get_all_remediations()
    # Filter for EXECUTED only
    executed = [r for r in remediations if r.get("status") == "EXECUTED"]
    
    # Attach current_monthly_cost from recommendations
    with sqlite3.connect(ss.db_path) as conn:
        conn.row_factory = sqlite3.Row
        for rem in executed:
            row = conn.execute("SELECT current_monthly_cost FROM recommendations WHERE id=?", (rem["recommendation_id"],)).fetchone()
            rem["current_monthly_cost"] = row["current_monthly_cost"] if row else None

    return {"remediations": executed, "total": len(executed)}

@app.post("/api/remediations/{rem_id}/rollback")
async def execute_rollback(rem_id: str):
    """Execute a rollback and revert recommendation status."""
    from core.state_store import StateStore
    import sqlite3
    
    ss = StateStore()
    
    # 1. Update remediation status to ROLLED_BACK
    with sqlite3.connect(ss.db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        # Get the recommendation_id for this remediation
        rem_row = conn.execute("SELECT recommendation_id, resource_id FROM remediations WHERE id=?", (rem_id,)).fetchone()
        if not rem_row:
            raise HTTPException(status_code=404, detail="Remediation not found")
            
        rec_id = rem_row["recommendation_id"]
        resource_id = rem_row["resource_id"]
        
        # Update remediation
        conn.execute("UPDATE remediations SET status='ROLLED_BACK' WHERE id=?", (rem_id,))
        conn.commit()
        
    # Revert recommendation using standard StateStore logic
    gov_row = ss.get_governance_decision(resource_id)
    target_status = gov_row["decision"] if gov_row else "PENDING_REVIEW"
    ss._execute("UPDATE recommendations SET status=?, executed_at=NULL WHERE id=?", (target_status, rec_id))
        
    return {"status": "success", "message": "Rollback successful"}

# ---------------------------------------------------------------------------
# POST /api/skill-submissions
# ---------------------------------------------------------------------------
@app.post("/api/skill-submissions")
async def create_skill_submission(request: Request):
    """Submit a new skill idea for review. Does NOT load or execute any code."""
    body = await request.json()
    store = StateStore()
    submission_id = store.create_skill_submission(
        skill_name=body["skill_name"],
        description=body["description"],
        track=body["track"],
        code_content=body["code_content"],
        submitted_by=body["submitted_by"],
    )
    return {"id": submission_id, "status": "pending"}


# ---------------------------------------------------------------------------
# GET /api/skill-submissions
# ---------------------------------------------------------------------------
@app.get("/api/skill-submissions")
async def list_skill_submissions(status: str = None):
    store = StateStore()
    return {"submissions": store.get_skill_submissions(status=status)}


# ---------------------------------------------------------------------------
# POST /api/skill-submissions/{submission_id}/approve
# POST /api/skill-submissions/{submission_id}/reject
# ---------------------------------------------------------------------------
@app.post("/api/skill-submissions/{submission_id}/approve")
async def approve_skill_submission(submission_id: str, request: Request, x_user_email: str = Header(None)):
    # SECURITY TODO: see core/admin_auth.py — X-User-Email is not yet cryptographically verified.
    store = StateStore()
    if not is_admin(x_user_email, store):
        raise HTTPException(status_code=403, detail="Not authorized to approve submissions")
    body = await request.json()
    store.review_skill_submission(submission_id, "approved", x_user_email, body.get("review_notes", ""))
    return {"status": "approved"}


@app.post("/api/skill-submissions/{submission_id}/reject")
async def reject_skill_submission(submission_id: str, request: Request, x_user_email: str = Header(None)):
    # SECURITY TODO: see core/admin_auth.py — X-User-Email is not yet cryptographically verified.
    store = StateStore()
    if not is_admin(x_user_email, store):
        raise HTTPException(status_code=403, detail="Not authorized to reject submissions")
    body = await request.json()
    store.review_skill_submission(submission_id, "rejected", x_user_email, body.get("review_notes", ""))
    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# GET /api/skill-admins, POST /api/skill-admins, DELETE /api/skill-admins/{email}
# ---------------------------------------------------------------------------
@app.get("/api/skill-admins")
async def list_skill_admins():
    store = StateStore()
    return {"admins": store.get_skill_admins(), "master_admin": get_master_admin()}


@app.post("/api/skill-admins")
async def add_skill_admin(request: Request, x_user_email: str = Header(None)):
    # SECURITY TODO: see core/admin_auth.py.
    if not is_master_admin(x_user_email):
        raise HTTPException(status_code=403, detail="Only the master admin can manage admins")
    body = await request.json()
    store = StateStore()
    store.add_skill_admin(body["email"], added_by=x_user_email)
    return {"status": "added"}


@app.delete("/api/skill-admins/{email}")
async def remove_skill_admin(email: str, x_user_email: str = Header(None)):
    # SECURITY TODO: see core/admin_auth.py.
    if not is_master_admin(x_user_email):
        raise HTTPException(status_code=403, detail="Only the master admin can manage admins")
    store = StateStore()
    store.remove_skill_admin(email)
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# GET /api/savings
# ---------------------------------------------------------------------------
@app.get("/api/savings")
async def get_savings():
    from core.state_store import StateStore

    ss = StateStore()
    savings = ss.get_savings_summary()

    # Calculate potential if all approved executed
    recs = ss.get_all_recommendations(status="APPROVED")
    potential = sum(r.get("estimated_monthly_saving", 0) or 0 for r in recs)

    # All recommendations total
    all_recs = ss.get_all_recommendations()
    total_identified = sum(r.get("estimated_monthly_saving", 0) or 0 for r in all_recs)

    # ROI calculation
    usage = ss.get_llm_usage_summary()
    gemini_cost = usage.get("estimated_cost_usd", 0.0)

    annual_saving = total_identified * 12
    annual_gemini_cost = gemini_cost * 12  # approximate

    return {
        "total_identified": round(total_identified, 2),
        "realized_savings": round(savings.get("realized_savings", 0), 2),
        "potential_if_all_executed": round(potential, 2),
        "total_remediations": savings.get("total_remediations", 0),
        "gemini_api_cost_usd": round(gemini_cost, 6),
        "annual_projected_savings": round(annual_saving, 2),
        "annual_gemini_cost": round(annual_gemini_cost, 6),
    }


# ---------------------------------------------------------------------------
# POST /api/chat — SSE stream
# ---------------------------------------------------------------------------
@app.post("/api/chat")
async def chat(request: Request):
    """FinOps Chat Agent — returns SSE stream."""
    from agents.finops_chat_agent import FinOpsChatAgent
    from api.sse import chat_event_generator

    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))

    agent = FinOpsChatAgent()
    return StreamingResponse(
        chat_event_generator(message, session_id, agent),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# GET /api/chat/history
# ---------------------------------------------------------------------------
@app.get("/api/chat/history")
async def chat_history(
    session_id: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
):
    from core.state_store import StateStore

    ss = StateStore()
    history = ss.get_conversation_history(session_id, limit=limit)
    return {"messages": history, "session_id": session_id}


# ---------------------------------------------------------------------------
# GET /api/tag-audit
# ---------------------------------------------------------------------------
@app.get("/api/tag-audit")
async def tag_audit():
    """Run Tag Compliance Reporter and return results."""
    try:
        from reporters.tag_compliance_reporter import TagComplianceReporter
        import pandas as pd

        tcr = TagComplianceReporter()
        report = tcr.generate_report()

        # The frontend expects 'has_env', 'has_owner', etc. in 'instances' list
        # Map 'missing_tags' to boolean fields for the UI
        records = []
        for inst in report.get("untagged_instances", []):
            missing = inst.get("missing_tags", [])
            inst_mapped = dict(inst)
            inst_mapped["has_env"] = "env" not in missing
            inst_mapped["has_owner"] = "owner" not in missing
            inst_mapped["has_team"] = "team" not in missing
            inst_mapped["has_app"] = "app" not in missing
            records.append(inst_mapped)

        return {
            "total_untagged": len(records),
            "csv_path": "", # Not strictly needed here, download uses its own endpoint
            "instances": records[:100],  # first 100 for display
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/tag-audit/download
# ---------------------------------------------------------------------------
@app.get("/api/tag-audit/download")
async def tag_audit_download():
    """Download the latest tag audit CSV."""
    import glob

    exports_dir = os.path.join(PROJECT_ROOT, "exports")
    pattern = os.path.join(exports_dir, "tag_audit_*.csv")
    files = sorted(glob.glob(pattern), reverse=True)

    if files:
        return FileResponse(
            files[0],
            media_type="text/csv",
            filename=os.path.basename(files[0]),
        )
    return JSONResponse({"error": "No tag audit CSV found. Run /api/tag-audit first."}, status_code=404)


# ---------------------------------------------------------------------------
# GET /api/nat-gateway
# ---------------------------------------------------------------------------
@app.get("/api/nat-gateway")
async def nat_gateway():
    """NAT Gateway cost breakdown."""
    import pandas as pd

    cache_path = os.path.join(PROJECT_ROOT, "cache", "nat_gateway_data.parquet")
    if not os.path.exists(cache_path):
        return JSONResponse({"error": "NAT Gateway data not found. Run /api/ingest first."}, status_code=404)

    df = pd.read_parquet(cache_path)
    total_90d = round(float(df["cost_90d"].sum()), 2)
    # Verified constant: NAT_MONTHLY = 118.96 = total / 3 months
    monthly = round(total_90d / 3, 2)

    gateways = []
    for _, row in df.sort_values("cost_90d", ascending=False).iterrows():
        gw = _sanitize_dict(row.to_dict())
        gw["monthly_cost"] = round(float(gw.get("cost_90d", 0)) / 3, 2)
        gateways.append(gw)

    return {
        "total_90d": total_90d,
        "monthly": monthly,
        "pct_of_total": 35.5,  # $356.89 / $1005.60 = 35.5%
        "gateway_count": len(gateways),
        "gateways": gateways,
        "insight": "NAT Gateway costs driven by EKS clusters pulling container images. "
                   "Recommend VPC endpoints for ECR/S3 to reduce NAT traversal.",
    }


# ---------------------------------------------------------------------------
# GET /api/anomalies
# ---------------------------------------------------------------------------
@app.get("/api/anomalies")
async def anomalies():
    """Cost anomaly detection."""
    try:
        from services.cost_anomaly_service import CostAnomalyService

        svc = CostAnomalyService()
        results = svc.detect_anomalies()
        return {"anomalies": results, "total": len(results)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/llm-usage
# ---------------------------------------------------------------------------
@app.get("/api/llm-usage")
async def llm_usage():
    """Gemini API usage stats."""
    from core.state_store import StateStore

    ss = StateStore()
    usage = ss.get_llm_usage_summary()

    return {
        "primary_model": "gemini-3.5-flash",
        "fallback_model": "gemini-3.1-flash",
        "total_calls": usage.get("total_calls", 0),
        "total_input_tokens": usage.get("total_input_tokens", 0),
        "total_output_tokens": usage.get("total_output_tokens", 0),
        "estimated_cost_usd": usage.get("estimated_cost_usd", 0.0),
        "by_agent": usage.get("by_agent", {}),
        "budget_limit": 50,
        "budget_remaining": max(0, 50 - usage.get("total_calls", 0)),
    }


# ---------------------------------------------------------------------------
# GET /api/what-if/{resource_id}
# ---------------------------------------------------------------------------
@app.get("/api/what-if/{resource_id}")
async def what_if(resource_id: str):
    """Spot conversion what-if simulator."""
    import os
    import pandas as pd
    instance = None
    if os.path.exists("cache/enriched_instances.parquet"):
        df = pd.read_parquet("cache/enriched_instances.parquet")
        matches = df[df["resource_id"] == resource_id]
        if not matches.empty:
            instance = _sanitize_dict(matches.iloc[0].to_dict())

    if not instance:
        return JSONResponse({"error": f"Instance {resource_id} not found"}, status_code=404)

    row = instance
    monthly = float(row.get("monthly_cost_est", 0) or 0)
    spot_saving = round(monthly * 0.65, 2)

    return {
        "resource_id": resource_id,
        "resource_name": str(row.get("resource_name", "")),
        "instance_type": str(row.get("instance_type", "")),
        "current_monthly": round(monthly, 2),
        "spot_monthly": round(monthly * 0.35, 2),
        "spot_saving_monthly": spot_saving,
        "spot_saving_annual": round(spot_saving * 12, 2),
        "saving_pct": 65.0,
        "is_eligible": bool(row.get("is_spot_eligible", False)),
        "eligibility_reason": (
            "Eligible — OnDemand, non-EKS, non-blocked"
            if row.get("is_spot_eligible")
            else f"Not eligible — {row.get('pricing_model', 'unknown')} pricing"
        ),
    }


# ---------------------------------------------------------------------------
# GET /api/fleet-summary
# ---------------------------------------------------------------------------
@app.get("/api/fleet-summary")
async def fleet_summary():
    """Latest AI-generated fleet summary."""
    from core.state_store import StateStore

    ss = StateStore()
    runs = ss.get_analysis_runs(limit=1)
    
    health = compute_fleet_health()

    if runs and runs[0].get("fleet_summary"):
        return {
            "summary": runs[0]["fleet_summary"],
            "generated_at": runs[0].get("completed_at"),
            "run_id": runs[0].get("run_id"),
            "fleet_health": health
        }

    return {
        "summary": "No fleet summary available. Click 'Run Analysis' to generate one.",
        "generated_at": None,
        "run_id": None,
        "fleet_health": health
    }


# ---------------------------------------------------------------------------
# GET /api/skills
# ---------------------------------------------------------------------------
@app.get("/api/skills")
async def skills():
    """Registered skills list."""
    from core.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.register_defaults()
    return registry.get_all_skills_summary()


# ---------------------------------------------------------------------------
# GET /api/spot-simulator/{search_term}
# ---------------------------------------------------------------------------
@app.get("/api/spot-simulator/{search_term}")
async def spot_simulator(search_term: str):
    """What-if Spot savings for a specific instance. Pure Python — no Gemini."""
    sim = SpotSimulator()
    return sim.simulate(search_term)


# ---------------------------------------------------------------------------
# GET /api/spot-simulator-fleet
# ---------------------------------------------------------------------------
@app.get("/api/spot-simulator-fleet")
async def spot_simulator_fleet():
    """Fleet-wide Spot savings potential. Pure Python — no Gemini."""
    sim = SpotSimulator()
    return sim.fleet_summary()


# ---------------------------------------------------------------------------
# GET /api/projection
# ---------------------------------------------------------------------------
@app.get("/api/projection")
async def projection():
    """30-day cost projection."""
    from core.state_store import StateStore

    ss = StateStore()

    # Dynamic: compute from live parquet data
    import os, pandas as pd
    current_monthly = 0.0
    if os.path.exists("cache/enriched_instances.parquet"):
        df = pd.read_parquet("cache/enriched_instances.parquet")
        if not df.empty and "monthly_cost_est" in df.columns:
            current_monthly = round(float(df["monthly_cost_est"].sum()), 2)

    # Get total savings from approved recommendations
    recs = ss.get_all_recommendations(status="APPROVED")
    total_saving = sum(r.get("estimated_monthly_saving", 0) or 0 for r in recs)
    optimised_monthly = round(current_monthly - total_saving, 2)

    # Generate 30 days of data
    current_trajectory = []
    optimised_trajectory = []
    for day in range(1, 31):
        daily_current = round(current_monthly / 30 * day, 2)
        daily_optimised = round(optimised_monthly / 30 * day, 2)
        current_trajectory.append({"day": day, "cost": daily_current})
        optimised_trajectory.append({"day": day, "cost": daily_optimised})

    return {
        "current_monthly": current_monthly,
        "optimised_monthly": optimised_monthly,
        "total_saving": round(total_saving, 2),
        "saving_pct": round(total_saving / current_monthly * 100, 1) if current_monthly > 0 else 0,
        "current_trajectory": current_trajectory,
        "optimised_trajectory": optimised_trajectory,
    }


# ============================================================
# AUDIT CENTER EXPORT ENDPOINTS
# ============================================================

from core.state_store import StateStore
state_store = StateStore()

@app.get("/api/export/recommendations")
async def export_recommendations():
    """Download all recommendations as CSV."""
    rows = state_store.get_all_recommendations()
    output = io.StringIO()
    if rows:
        fieldnames = ["resource_name", "instance_type", "region", "track", "action",
                      "current_monthly_cost", "estimated_monthly_saving", "saving_pct",
                      "confidence", "status", "gate_tier", "gate_reason",
                      "has_performance_data", "skill_name", "created_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=recommendations.csv"},
    )


@app.get("/api/export/governance")
async def export_governance():
    """Download all governance decisions as CSV."""
    rows = state_store.get_all_governance_decisions()
    output = io.StringIO()
    if rows:
        fieldnames = ["resource_name", "resource_id", "decision", "tier",
                      "reason", "assessed_at", "human_override", "human_override_reason"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=governance_decisions.csv"},
    )


@app.get("/api/export/llm-usage")
async def export_llm_usage():
    """Download all Gemini API call logs as CSV."""
    rows = state_store._fetchall("SELECT * FROM llm_usage ORDER BY called_at DESC")
    output = io.StringIO()
    if rows:
        fieldnames = ["agent", "resource_id", "model", "input_tokens",
                      "output_tokens", "estimated_cost_usd", "called_at", "run_id"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gemini_usage.csv"},
    )


@app.get("/api/export/remediations")
async def export_remediations():
    """Download all remediations (executed scripts) as CSV."""
    rows = state_store.get_all_remediations()
    output = io.StringIO()
    if rows:
        fieldnames = ["resource_name", "resource_id", "action_taken",
                      "realized_saving", "status", "executed_by", "executed_at",
                      "recommendation_id"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=remediations.csv"},
    )


@app.get("/api/export/audit-summary")
async def export_audit_summary():
    """Return live preview data for the Audit Center tab (JSON, not CSV)."""
    # Recommendations preview (first 5 rows)
    recs = state_store.get_all_recommendations()
    recs_preview = [{
        "resource_name": r.get("resource_name", "") or r.get("resource_id", "Unknown"),
        "track": r.get("track", ""),
        "status": r.get("status", ""),
        "estimated_monthly_saving": r.get("estimated_monthly_saving", 0),
        "gate_tier": r.get("gate_tier"),
        "created_at": r.get("created_at", ""),
    } for r in recs[:5]]

    # Governance preview (first 5 rows)
    gov = state_store.get_all_governance_decisions()
    gov_preview = [{
        "resource_name": r.get("resource_name", "") or r.get("resource_id", "Unknown"),
        "resource_id": r.get("resource_id", ""),
        "decision": r.get("decision", ""),
        "tier": r.get("tier"),
        "reason": (r.get("reason", "") or "")[:80] + "..." if len(r.get("reason", "") or "") > 80 else r.get("reason", ""),
        "assessed_at": r.get("assessed_at", ""),
    } for r in gov[:5]]

    # LLM usage preview (first 5 rows)
    llm = state_store._fetchall("SELECT * FROM llm_usage ORDER BY called_at DESC LIMIT 5")
    llm_preview = [{
        "agent": r.get("agent", ""),
        "model": r.get("model", ""),
        "input_tokens": r.get("input_tokens", 0),
        "output_tokens": r.get("output_tokens", 0),
        "estimated_cost_usd": r.get("estimated_cost_usd", 0),
        "called_at": r.get("called_at", ""),
    } for r in llm]

    # Remediations preview (all — usually small count)
    rems = state_store.get_all_remediations()
    rems_preview = [{
        "resource_name": r.get("resource_name", ""),
        "action_taken": r.get("action_taken", ""),
        "realized_saving": r.get("realized_saving"),
        "status": r.get("status", ""),
        "executed_at": r.get("executed_at", ""),
    } for r in rems[:5]]

    # Counts
    llm_all = state_store._fetchall("SELECT COUNT(*) as cnt, SUM(estimated_cost_usd) as total_cost FROM llm_usage")
    llm_stats = llm_all[0] if llm_all else {"cnt": 0, "total_cost": 0}

    return {
        "recommendations": {
            "total": len(recs),
            "preview": recs_preview,
            "blocked": sum(1 for r in recs if r.get("status") == "BLOCKED"),
            "flagged": sum(1 for r in recs if r.get("status") == "FLAGGED"),
            "approved": sum(1 for r in recs if r.get("status") == "APPROVED"),
        },
        "governance": {
            "total": len(gov),
            "preview": gov_preview,
        },
        "llm_usage": {
            "total_calls": int(llm_stats.get("cnt", 0)),
            "total_cost_usd": round(float(llm_stats.get("total_cost", 0) or 0), 4),
            "preview": llm_preview,
        },
        "remediations": {
            "total": len(rems),
            "preview": rems_preview,
        },
    }

@app.get("/api/v1/instances/{instance_id}/details")
async def get_instance_details(instance_id: str, account: str = "opstree"):
    """
    Returns rich instance details by combining:
    - UnitEconPro metadata (platform, arch, AZ, CPU P95, AMI, etc)
    - UnitEconPro lifecycle (age, active days, total hours, gaps)
    - Cloud Sentry recommendations for this instance
    - Cloud Sentry governance decision for this instance
    Called on-demand when frontend opens instance detail panel.
    """
    from core.uniteconpro_client import get_full_ec2_data
    from core.state_store import StateStore
    import json

    store = StateStore()

    # 1. Fetch from UnitEconPro
    ue_data = get_full_ec2_data(instance_id, account=account)
    metadata = ue_data.get("metadata") or {}
    lifecycle = ue_data.get("lifecycle") or {}

    # 2. Get Cloud Sentry recommendations for this instance
    all_recs = store.get_all_recommendations()
    instance_recs = [
        r for r in all_recs
        if r.get("resource_id") == instance_id
    ]

    # Parse confidence_reasons from JSON string to list
    for rec in instance_recs:
        raw = rec.get("confidence_reasons", "[]")
        try:
            rec["confidence_reasons"] = json.loads(raw) \
                if isinstance(raw, str) else (raw or [])
        except Exception:
            rec["confidence_reasons"] = []

    # 3. Get governance decision for this instance
    all_govs = store.get_governance_decisions() \
        if hasattr(store, 'get_governance_decisions') else []
    gov_decision = next(
        (g for g in all_govs if g.get("resource_id") == instance_id),
        None
    )

    return {
        # Identity
        "instance_id": instance_id,
        "instance_name": lifecycle.get("instance_name", ""),
        "instance_type": metadata.get("instance_type", ""),
        "platform": metadata.get("platform", ""),
        "architecture": metadata.get("architecture", ""),
        "pricing_model": metadata.get("pricing_model", ""),
        "inferred_state": metadata.get("inferred_state", ""),
        "criticality": metadata.get("criticality", ""),

        # Location
        "region": metadata.get("region", ""),
        "availability_zone": metadata.get("availability_zone", ""),
        "account_name": metadata.get("account_name", ""),
        "aws_account_id": metadata.get("aws_account_id", ""),

        # Performance
        "cpu_avg_pct": metadata.get("cpu_avg_pct"),
        "cpu_max_pct": metadata.get("cpu_max_pct"),
        "cpu_p95_pct": metadata.get("cpu_p95_pct"),
        "net_in_mbps": metadata.get("net_in_mbps"),
        "net_out_mbps": metadata.get("net_out_mbps"),
        "rightsizing_signal": metadata.get("rightsizing_signal", ""),
        "utilization_days": metadata.get("utilization_days"),
        "graviton_migration_candidate": 
            metadata.get("graviton_migration_candidate", False),

        # Storage
        "ebs_optimized": metadata.get("ebs_optimized", False),
        "attached_ebs_count": metadata.get("attached_ebs_count", 0),
        "root_volume_type": metadata.get("root_volume_type", ""),
        "root_volume_size_gb": metadata.get("root_volume_size_gb", 0),

        # AMI
        "image_id": metadata.get("image_id", ""),
        "ami_name": metadata.get("ami_name", ""),
        "ami_state": metadata.get("ami_state", ""),
        "ami_is_public": metadata.get("ami_is_public", False),

        # Network
        "has_public_ip": metadata.get("has_public_ip", False),
        "detailed_monitoring": metadata.get("detailed_monitoring", False),

        # Lifecycle
        "first_seen": lifecycle.get("first_seen", ""),
        "last_launch_time": metadata.get("last_launch_time", ""),
        "instance_age_days": lifecycle.get("instance_age_days"),
        "active_days": lifecycle.get("active_days"),
        "stopped_days": lifecycle.get("stopped_days"),
        "avg_weekday_hours": lifecycle.get("avg_weekday_hours"),
        "avg_weekend_hours": lifecycle.get("avg_weekend_hours"),
        "total_hours": lifecycle.get("total_hours"),
        "total_cost": lifecycle.get("total_cost"),
        "gaps": lifecycle.get("gaps", []),

        # Tags and insight
        "tags": metadata.get("tags", {}),
        "insight": metadata.get("insight", ""),
        "cost_flags": metadata.get("cost_flags", []),

        # Cloud Sentry data
        "recommendations": instance_recs,
        "governance_decision": gov_decision,
    }

@app.patch("/api/recommendations/{rec_id}/status")
async def update_recommendation_status(
    rec_id: str, request: Request
):
    """
    Update recommendation status.
    Called by frontend Approve/Ignore buttons.
    Body: { "status": "APPROVED" | "IGNORED" }
    Returns the full updated recommendation.
    """
    try:
        body = await request.json()
        new_status = body.get("status", "").upper()

        valid_statuses = {
            "APPROVED", "IGNORED",
            "PENDING_REVIEW", "FLAGGED"
        }
        if new_status not in valid_statuses:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Invalid status '{new_status}'. "
                             f"Must be one of: "
                             f"{', '.join(sorted(valid_statuses))}"
                }
            )

        state_store.update_recommendation_status(
            rec_id, new_status
        )

        updated = state_store.get_recommendation(rec_id)
        if not updated:
            return JSONResponse(
                status_code=404,
                content={
                    "error": f"Recommendation {rec_id} not found"
                }
            )

        import json as _json
        raw = updated.get("confidence_reasons", "[]")
        try:
            updated["confidence_reasons"] = _json.loads(raw) \
                if isinstance(raw, str) else (raw or [])
        except Exception:
            updated["confidence_reasons"] = []

        return JSONResponse(content={
            "success": True,
            "recommendation": updated,
            "message": f"Status updated to {new_status}"
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/api/export/analysis-runs")
async def export_analysis_runs():
    """
    Download all analysis runs as CSV.
    Fixes the broken Download CSV button 
    in Audit Log page.
    """
    import csv
    import io as _io

    rows = state_store.get_analysis_runs(limit=500)
    output = _io.StringIO()

    if rows:
        fieldnames = [
            "run_id", "started_at", "completed_at",
            "instances_analysed",
            "recommendations_generated",
            "blocked_count", "flagged_count",
            "approved_count", "gemini_calls_total",
            "estimated_gemini_cost_usd", "status"
        ]
        writer = csv.DictWriter(
            output, fieldnames=fieldnames,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=analysis_runs.csv"
        }
    )
