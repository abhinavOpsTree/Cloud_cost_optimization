"""
agents/finops_analyst_agent.py
-------------------------------
FinOps Analyst Agent — runs all analysis skills and generates recommendations.

This IS an AI Agent (generates fleet summary via Gemini).

Pipeline:
  1. Load enriched instances from parquet
  2. Check remediations table — skip already-remediated instances
  3. Run all ANALYSIS_SKILLS against each instance
  4. Save recommendations to SQLite
  5. Run governance agent to set status on each recommendation
  6. Generate fleet summary via Gemini
  7. Store fleet summary in analysis_runs table

Memory: checks remediations table before recommending (skip if REMEDIATED).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from core.state_store import StateStore
from core.llm_client import call_gemini, reset_run_counters
from skills.analysis.rightsizing import RightsizingSkill
from skills.analysis.spot_conversion import SpotConversionSkill
from skills.analysis.schedule_policy import SchedulePolicySkill
from skills.analysis.eks_diagnosis import EKSDiagnosisSkill

# Cap concurrent Gemini API requests to avoid rate-limit bursts
MAX_CONCURRENT_WORKERS = 5


def _build_confidence_reasons(
    has_performance_data: bool,
    cpu_avg: float | None,
    confidence_band: str,
    confidence: float
) -> list:
    """
    Builds human-readable reasons explaining the confidence score.
    Uses only variables available at the injection point.
    Returns list of 3-4 strings. Never raises.
    """
    reasons = []
    try:
        if has_performance_data:
            reasons.append(
                "Real CloudWatch data available (90 days)"
            )
        else:
            reasons.append(
                "No CloudWatch data — based on cost pattern "
                "and instance type heuristics only"
            )

        if cpu_avg is not None:
            if cpu_avg < 15:
                reasons.append(
                    f"CPU consistently low "
                    f"(avg {cpu_avg:.1f}%, well below 15% threshold)"
                )
            elif cpu_avg < 40:
                reasons.append(
                    f"CPU moderately utilised (avg {cpu_avg:.1f}%)"
                )
            else:
                reasons.append(
                    f"CPU utilisation high (avg {cpu_avg:.1f}%) "
                    f"— review carefully before approving"
                )
        else:
            reasons.append(
                "CPU metrics unavailable — "
                "confidence reduced accordingly"
            )

        if confidence_band == "green":
            reasons.append(
                "Strong consistent underutilisation pattern "
                "detected across observation window"
            )
        elif confidence_band == "amber":
            reasons.append(
                "Moderate signal strength — "
                "some variability in utilisation observed"
            )
        elif confidence_band == "red":
            reasons.append(
                "Weak signal — high variability detected, "
                "manual review strongly recommended"
            )

    except Exception:
        pass

    return reasons[:4]


class FinOpsAnalystAgent:
    """
    Runs analysis skills and generates cost optimization recommendations.

    Usage:
        agent = FinOpsAnalystAgent()
        stats = agent.run()
    """

    def __init__(self):
        self.store = StateStore()
        self.skills = [
            RightsizingSkill(),
            SpotConversionSkill(),
            SchedulePolicySkill(),
            EKSDiagnosisSkill(),
        ]

    def run(
        self,
        cache_path: str = "cache/enriched_instances.parquet",
        run_id: Optional[str] = None,
        progress_callback=None,
    ) -> Dict:
        """
        Run the full analysis pipeline.

        Returns stats dict with counts.
        """
        if run_id is None:
            run_id = self.store.start_analysis_run()

        reset_run_counters()
        self.store.clear_unexecuted_recommendations()

        if not os.path.exists(cache_path):
            print("[ANALYST] ERROR: enriched_instances.parquet not found.")
            return {"error": "No enriched data", "recommendations_generated": 0}

        df = pd.read_parquet(cache_path)
        total_instances = len(df)
        print(f"[ANALYST] Analysing {total_instances} instances with {len(self.skills)} skills")

        if progress_callback:
            progress_callback(0, total_instances, "Analyzing Instances")

        # Get already-remediated resources
        remediations = self.store.get_all_remediations()
        remediated_ids = {r["resource_id"] for r in remediations if r.get("status") == "EXECUTED"}

        total_recs = 0
        skill_stats = {}
        _stats_lock = threading.Lock()
        _processed_count = 0

        def _analyse_instance(idx, row):
            """Analyse a single instance — designed to run in a thread."""
            nonlocal total_recs, _processed_count

            # Each thread gets its own StateStore (fresh SQLite connection)
            thread_store = StateStore()

            instance = row.to_dict()
            resource_id = str(instance.get("resource_id", ""))
            resource_name = str(instance.get("resource_name", ""))

            # Parse all_tags
            tags_raw = instance.get("all_tags", "{}")
            if isinstance(tags_raw, str):
                try:
                    instance["all_tags"] = json.loads(tags_raw)
                except Exception:
                    instance["all_tags"] = {}

            # Skip already remediated
            if resource_id in remediated_ids:
                with _stats_lock:
                    _processed_count += 1
                    if progress_callback:
                        progress_callback(_processed_count, total_instances, "Analyzing Instances")
                return

            # Skip dead instances
            if instance.get("lifecycle_state") == "Terminated":
                with _stats_lock:
                    _processed_count += 1
                    if progress_callback:
                        progress_callback(_processed_count, total_instances, "Analyzing Instances")
                return

            # Run each skill
            for skill in self.skills:
                skill_name = skill.NAME
                start_ms = time.time()

                try:
                    if not skill.can_apply(instance):
                        continue

                    finding = skill.analyse(instance)
                    if not finding:
                        thread_store.save_skill_result({
                            "run_id": run_id,
                            "skill_name": skill_name,
                            "resource_id": resource_id,
                            "applied": True,
                            "finding": finding,
                            "recommendation_generated": False,
                            "execution_time_ms": int((time.time() - start_ms) * 1000),
                        })
                        continue

                    recommendation = skill.recommend(instance, finding)
                    if not recommendation:
                        thread_store.save_skill_result({
                            "run_id": run_id,
                            "skill_name": skill_name,
                            "resource_id": resource_id,
                            "applied": True,
                            "finding": finding,
                            "recommendation_generated": False,
                            "execution_time_ms": int((time.time() - start_ms) * 1000),
                        })
                        continue

                    # Generate full AI Suggestion
                    action = recommendation.get("action", "")
                    heuristic_reason = recommendation.get("rationale", "")
                    est_savings = recommendation.get("estimated_monthly_saving", 0.0)
                    cpu_p95 = instance.get("cpu_p95_pct", "N/A")
                    
                    suggestion_prompt = f"""Explain why the following AWS EC2 optimization recommendation was made.
                    Instance: {resource_name} ({instance.get("instance_type", "")})
                    Action: {action}
                    Rationale from rules: {heuristic_reason}
                    Estimated Monthly Saving: ${est_savings}
                    CPU p95: {cpu_p95}%
                    Write exactly one concise paragraph explaining why this is a safe and cost-effective move. Be highly professional and data-driven."""
                    
                    ai_suggestion = call_gemini(
                        prompt=suggestion_prompt, 
                        agent="finops_analyst", 
                        resource_id=resource_id, 
                        run_id=run_id
                    )

                    # Build full recommendation record
                    rec_id = f"rec-{resource_id}-{recommendation.get('track', 'unknown')}"
                    rec = {
                        "id": rec_id,
                        "resource_id": resource_id,
                        "resource_name": resource_name,
                        "instance_type": instance.get("instance_type", ""),
                        "region": instance.get("region", ""),
                        "track": recommendation.get("track", ""),
                        "action": action,
                        "current_monthly_cost": recommendation.get("current_monthly_cost", 0.0),
                        "estimated_monthly_saving": est_savings,
                        "saving_pct": recommendation.get("saving_pct", 0.0),
                        "confidence": recommendation.get("confidence", 0.0),
                        "rationale": ai_suggestion,
                        "status": "PENDING_REVIEW",
                        "has_performance_data": instance.get("has_performance_data", False),
                        "cpu_avg_pct": instance.get("cpu_avg_pct"),
                        "skill_name": recommendation.get("skill_name", skill_name),
                        "created_at": datetime.utcnow().isoformat(),
                    }

                    confidence_reasons = _build_confidence_reasons(
                        has_performance_data=bool(
                            instance.get("has_performance_data", False)
                        ),
                        cpu_avg=instance.get("cpu_avg_pct"),
                        confidence_band=recommendation.get(
                            "confidence_band", "amber"
                        ),
                        confidence=recommendation.get("confidence", 0.0)
                    )
                    rec["confidence_reasons"] = json.dumps(
                        confidence_reasons
                    )

                    thread_store.save_recommendation(rec)

                    with _stats_lock:
                        total_recs += 1
                        skill_stats[skill_name] = skill_stats.get(skill_name, 0) + 1

                    thread_store.save_skill_result({
                        "run_id": run_id,
                        "skill_name": skill_name,
                        "resource_id": resource_id,
                        "applied": True,
                        "finding": finding,
                        "recommendation_generated": True,
                        "execution_time_ms": int((time.time() - start_ms) * 1000),
                    })

                except Exception as e:
                    print(f"[ANALYST] Skill {skill_name} failed on {resource_name}: {e}")

            # Update progress after this instance is fully processed
            with _stats_lock:
                _processed_count += 1
                if progress_callback:
                    progress_callback(_processed_count, total_instances, "Analyzing Instances")

        # ---- Run instances concurrently ----
        rows_with_idx = list(enumerate(df.iterrows()))
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
            futures = {
                executor.submit(_analyse_instance, idx, row): idx
                for idx, (_, row) in rows_with_idx
            }
            for future in as_completed(futures):
                # Propagate any unhandled exception from threads
                try:
                    future.result()
                except Exception as e:
                    print(f"[ANALYST] Thread error for instance idx={futures[future]}: {e}")

        print(f"\n[ANALYST] === ANALYSIS SUMMARY ===")
        print(f"  Total recommendations: {total_recs}")
        for skill_name, count in skill_stats.items():
            print(f"  {skill_name}: {count}")

        # ----------------------------------------------------------
        # Run governance on all recommendations
        # ----------------------------------------------------------
        self._run_governance(run_id, progress_callback=progress_callback)

        # ----------------------------------------------------------
        # Generate fleet summary via Gemini
        # ----------------------------------------------------------
        instances = df.to_dict('records')
        fleet_summary = self._generate_fleet_summary(run_id, instances)

        # Update analysis run
        recs_after_gov = self.store.get_all_recommendations()
        blocked = sum(1 for r in recs_after_gov if r["status"] == "BLOCKED")
        flagged = sum(1 for r in recs_after_gov if r["status"] == "FLAGGED")
        approved = sum(1 for r in recs_after_gov if r["status"] == "APPROVED")

        self.store.complete_analysis_run(run_id, {
            "instances_analysed": len(df),
            "recommendations_generated": total_recs,
            "blocked_count": blocked,
            "flagged_count": flagged,
            "approved_count": approved,
            "fleet_summary": fleet_summary,
        })

        return {
            "run_id": run_id,
            "instances_analysed": len(df),
            "recommendations_generated": total_recs,
            "blocked_count": blocked,
            "flagged_count": flagged,
            "approved_count": approved,
            "skill_stats": skill_stats,
        }

    def _run_governance(self, run_id: str, progress_callback=None) -> None:
        """Apply governance decisions to all recommendations."""
        from agents.governance_agent import GovernanceAgent

        ga = GovernanceAgent()
        recs = self.store.get_all_recommendations()
        
        # Load instances for governance lookup
        df = pd.read_parquet("cache/enriched_instances.parquet")
        instances_by_id = {}
        for _, row in df.iterrows():
            inst = row.to_dict()
            tags_raw = inst.get("all_tags", "{}")
            if isinstance(tags_raw, str):
                try:
                    inst["all_tags"] = json.loads(tags_raw)
                except Exception:
                    inst["all_tags"] = {}
            instances_by_id[str(inst.get("resource_id", ""))] = inst

        rec_resource_ids = {rec.get("resource_id", "") for rec in recs}
        total_pending = len(recs)
        if progress_callback:
            progress_callback(0, total_pending, "Evaluating Governance")

        import concurrent.futures

        def process_rec(rec, idx):
            resource_id = rec.get("resource_id", "")
            instance = instances_by_id.get(resource_id, {})
            if not instance:
                return None
            decision = ga.evaluate_single(instance, rec)
            if progress_callback and idx % 5 == 0:
                progress_callback(idx, total_pending, "Evaluating Governance")
            return rec["id"], decision

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(process_rec, rec, i) for i, rec in enumerate(recs)]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    rec_id, decision = result
                    status = decision.get("status", "PENDING_REVIEW")
                    tier = decision.get("tier")
                    reason = decision.get("reason", "")
                    
                    self.store.update_recommendation_status(
                        rec_id, status, gate_tier=tier, gate_reason=reason
                    )

        # Generate protective recommendations for any HARD_BLOCKED instances 
        # that didn't trigger any other skills, so they appear in the UI
        from skills.governance.production_shield import ProductionShieldSkill
        from datetime import datetime
        ps = ProductionShieldSkill()

        for resource_id, instance in instances_by_id.items():
            if resource_id not in rec_resource_ids:
                decision = ps.evaluate(instance, {})
                if decision and decision.get("status") == "BLOCKED":
                    rec = {
                        "id": f"rec-{resource_id}-protection",
                        "resource_id": resource_id,
                        "resource_name": instance.get("resource_name", ""),
                        "instance_type": instance.get("instance_type", ""),
                        "region": instance.get("region", ""),
                        "track": "protection",
                        "action": "Protected from modification",
                        "current_monthly_cost": instance.get("monthly_cost_est", 0.0) or 0.0,
                        "estimated_monthly_saving": 0.0,
                        "saving_pct": 0.0,
                        "confidence": 1.0,
                        "rationale": decision.get("reason", "Protected by Production Shield"),
                        "status": "BLOCKED",
                        "gate_tier": decision.get("tier", 1),
                        "gate_reason": decision.get("reason", "Protected"),
                        "has_performance_data": bool(instance.get("has_performance_data")),
                        "skill_name": "production_shield",
                        "created_at": datetime.utcnow().isoformat(),
                        "confidence_reasons": json.dumps([
                            "Production Shield — Tier 1 hard block",
                            "Production environment tag detected",
                            "No override permitted regardless of metrics"
                        ]),
                    }
                    self.store.save_recommendation(rec)

        if progress_callback:
            progress_callback(total_pending, total_pending, "Generating Summary")

    def _generate_fleet_summary(self, run_id: str, instances: list) -> str:
        """Generate fleet summary using Gemini."""
        try:
            recs = self.store.get_all_recommendations()
            by_track = {}
            for r in recs:
                track = r.get("track", "unknown")
                by_track.setdefault(track, []).append(r)

            spot_count = len(by_track.get("spot", []))
            spot_saving = sum(r.get("estimated_monthly_saving", 0) for r in by_track.get("spot", []))
            rightsize_count = len(by_track.get("rightsizing", []))
            schedule_count = len(by_track.get("schedule", []))
            eks_count = len(by_track.get("eks", []))

            blocked = sum(1 for r in recs if r["status"] == "BLOCKED")
            flagged = sum(1 for r in recs if r["status"] == "FLAGGED")
            approved = sum(1 for r in recs if r["status"] == "APPROVED")

            import json
            import os
            
            global_instances = len(instances)
            global_cost = sum(inst.get("monthly_cost_est", 0) for inst in instances)
            
            # Build clear stats to prevent AI hallucination
            analyzed_count = len(instances)
            missing_metrics = sum(1 for inst in instances if not inst.get("has_performance_data", False))
            with_metrics = analyzed_count - missing_metrics
            
            monthly_ec2_run_rate = sum(inst.get("monthly_cost_est", 0) for inst in instances)
            
            import pandas as pd
            nat_spend_monthly = 0.0
            total_active_instances = analyzed_count
            historical_instances = analyzed_count
            
            # Get true global fleet counts if available
            if os.path.exists("cache/enriched_instances.parquet"):
                try:
                    df = pd.read_parquet("cache/enriched_instances.parquet")
                    if not df.empty and "resource_id" in df.columns:
                        historical_instances = df["resource_id"].nunique()
                        if "lifecycle_state" in df.columns:
                            total_active_instances = df[df["lifecycle_state"] != "Terminated"]["resource_id"].nunique()
                        else:
                            total_active_instances = historical_instances
                except:
                    pass
                    
            if os.path.exists("cache/nat_gateway_data.parquet"):
                df_nat = pd.read_parquet("cache/nat_gateway_data.parquet")
                nat_spend_monthly = float(df_nat["cost_90d"].sum()) / 3 if not df_nat.empty else 0.0

            nat_line = f"- NAT Gateway Monthly Cost: ${nat_spend_monthly:.2f}\n" if nat_spend_monthly > 0 else ""

            prompt = f"""Write a brief 3-paragraph FinOps optimization summary for OpsTree's AWS account.

IMPORTANT VERIFIED DATA (Use these exact numbers, do not make up or estimate any numbers):
- Global Fleet Size: {total_active_instances} active EC2 instances
- Historical Fleet Size: {historical_instances} total instances seen over the last 90 days.
- Instances Analyzed for Optimization: {analyzed_count} (we only analyzed the top highest-cost instances)
- Monthly Run Rate of Analyzed Instances: ${monthly_ec2_run_rate:.2f}/month
- Telemetry Status: {with_metrics} instances have CloudWatch metrics available, {missing_metrics} instances are missing telemetry.
- Recommendations Generated: {len(recs)} total
- Spot Conversion Opportunities: {spot_count} instances (potential savings: ~${spot_saving:.2f}/month)
- Rightsizing Opportunities: {rightsize_count}
- Schedule Optimization Opportunities: {schedule_count}
- EKS Cluster Opportunities: {eks_count}
- Governance Review: {blocked} blocked (exempt), {flagged} flagged for review, {approved} approved automatically
{nat_line}
INSTRUCTIONS:
1. Write exactly 3 short paragraphs.
2. Be precise with the numbers provided above.
3. CRITICAL: In the final paragraph, you MUST explicitly state that {missing_metrics} instances are currently missing CloudWatch telemetry data and were safely excluded from rightsizing analysis. State clearly that proper rightsizing will be performed when CPU metrics become available.
4. CRITICAL: Mention that AI recommendations are generated for the current active instances only. You should explicitly point out the difference between the {total_active_instances} currently active instances and the {historical_instances} historical instances, and note that we could have saved a higher percentage from last months when the running instances were {historical_instances}."""

            summary = call_gemini(
                prompt=prompt,
                agent="finops_analyst",
                resource_id="fleet_summary",
                run_id=run_id,
            )
            return summary

        except Exception as e:
            print(f"[ANALYST] Fleet summary generation failed: {e}")
            return "Fleet summary unavailable."
