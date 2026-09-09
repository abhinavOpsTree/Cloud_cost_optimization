"""
skills/context/savings_context.py
Loads current savings and remediation data as context for the chat agent.
"""
from __future__ import annotations

from core.base_skill import BaseContextSkill


class SavingsContextSkill(BaseContextSkill):
    NAME = "savings_context"
    DISPLAY_NAME = "Savings Context"

    def load_context(self, instances: list = None) -> str:
        try:
            from core.state_store import StateStore
            ss = StateStore()

            recs = ss.get_all_recommendations()
            remediations = ss.get_all_remediations()

            if not recs:
                return "No analysis has been run yet. No recommendations available."

            # Track counts
            by_track = {}
            by_status = {}
            total_saving = 0.0
            for r in recs:
                track = r.get("track", "unknown")
                status = r.get("status", "PENDING_REVIEW")
                saving = r.get("estimated_monthly_saving", 0) or 0
                by_track[track] = by_track.get(track, 0) + 1
                by_status[status] = by_status.get(status, 0) + 1
                if status == "APPROVED":
                    total_saving += saving

            # Spot savings
            spot_recs = [r for r in recs if r.get("track") == "spot"]
            spot_saving = sum(r.get("estimated_monthly_saving", 0) or 0 for r in spot_recs)

            lines = [
                "SAVINGS & RECOMMENDATIONS SUMMARY",
                f"Total recommendations: {len(recs)}",
                f"",
                "By track:",
            ]
            for track, count in sorted(by_track.items()):
                lines.append(f"  - {track}: {count} recommendations")

            lines.append("")
            lines.append("By status:")
            for status, count in sorted(by_status.items()):
                lines.append(f"  - {status}: {count}")

            lines.append("")
            lines.append(f"Spot conversion: {len(spot_recs)} instances, ~${spot_saving:.2f}/month potential")
            lines.append(f"Total approved savings potential: ~${total_saving:.2f}/month")
            lines.append(f"Remediations executed: {len(remediations)}")
            realized = sum(r.get("realized_saving") or 0 for r in remediations)
            if realized > 0:
                lines.append(f"Realized savings: ${realized:.2f}/month")

            return "\n".join(lines)

        except Exception as e:
            return f"Error loading savings context: {e}"
