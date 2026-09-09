"""
services/report_generation_service.py
Report generation for Cloud-Sentry AI analysis runs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Optional


class ReportGenerationService:
    """Generates summary reports from analysis runs."""

    def generate_report(self, run_id: Optional[str] = None) -> Dict:
        """Generate a comprehensive report from the latest analysis run."""
        from core.state_store import StateStore
        ss = StateStore()

        recs = ss.get_all_recommendations()
        remediations = ss.get_all_remediations()
        runs = ss.get_analysis_runs(limit=1)

        # Categorize recommendations
        by_track = {}
        by_status = {}
        total_potential = 0.0

        for r in recs:
            track = r.get("track", "unknown")
            status = r.get("status", "PENDING_REVIEW")
            saving = r.get("estimated_monthly_saving", 0) or 0

            by_track.setdefault(track, {"count": 0, "saving": 0.0})
            by_track[track]["count"] += 1
            by_track[track]["saving"] += saving

            by_status[status] = by_status.get(status, 0) + 1
            total_potential += saving

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id or (runs[0]["run_id"] if runs else None),
            "total_recommendations": len(recs),
            "total_potential_monthly_saving": round(total_potential, 2),
            "by_track": by_track,
            "by_status": by_status,
            "remediations_executed": len(remediations),
            "realized_savings": round(
                sum(r.get("realized_saving") or 0 for r in remediations), 2
            ),
            "fleet_summary": runs[0].get("fleet_summary") if runs else None,
        }

    def export_csv(self, output_dir: str = "exports") -> str:
        """Export recommendations to CSV."""
        from core.state_store import StateStore
        import pandas as pd

        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(output_dir, f"recommendations_{timestamp}.csv")

        ss = StateStore()
        recs = ss.get_all_recommendations()
        if recs:
            df = pd.DataFrame(recs)
            df.to_csv(csv_path, index=False)
        return csv_path
