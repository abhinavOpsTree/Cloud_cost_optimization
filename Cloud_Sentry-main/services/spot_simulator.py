"""
services/spot_simulator.py
---------------------------
Spot pricing what-if simulator using real 89-day billing data.

Pure Python. Zero Gemini calls.
Reads enriched_instances.parquet.

Used by:
  - GET /api/spot-simulator/{resource_name}
  - FinOpsChatAgent (deterministic fast path for Spot questions)
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd


PARQUET_PATH = "cache/enriched_instances.parquet"
SPOT_SAVING_PCT = 65.0   # 65% cheaper than OnDemand
PILOT_DAYS = 89


class SpotSimulator:
    """
    What-if Spot pricing calculator using real billing data.

    Usage:
        sim = SpotSimulator()
        result = sim.simulate("bp-testing-windows")
    """

    def simulate(self, search_term: str) -> dict:
        """
        Calculate Spot savings for a named instance.

        Returns:
            {
                found: bool,
                resource_name: str,
                resource_id: str,
                instance_type: str,
                pricing_model: str,         # current pricing
                is_blocked: bool,           # True if HARD_BLOCK — cannot convert
                is_spot_eligible: bool,
                ondemand_cost_90d: float,   # actual cost from billing data
                ondemand_monthly: float,
                spot_cost_90d: float,       # estimated at 35% of OnDemand
                spot_monthly: float,
                missed_saving_90d: float,
                missed_saving_monthly: float,
                annual_projection: float,
                saving_pct: float,          # always 65%
                note: str,                  # human-readable summary
            }
        """
        if not os.path.exists(PARQUET_PATH):
            return {"found": False, "error": "No fleet data. Run analysis first."}

        try:
            df = pd.read_parquet(PARQUET_PATH)
        except Exception as e:
            return {"found": False, "error": f"Could not read fleet data: {e}"}

        # Search by name (partial, case-insensitive) or exact resource_id
        search_lower = search_term.strip().lower()
        mask = (
            df["resource_name"].str.lower().str.contains(search_lower, na=False) |
            (df["resource_id"].str.lower() == search_lower)
        )
        matches = df[mask]

        if matches.empty:
            return {"found": False, "error": f"No instance found matching '{search_term}'."}

        # Pick highest-cost match
        row = matches.loc[matches["total_cost_90d"].fillna(0).idxmax()]

        resource_name = str(row.get("resource_name", ""))
        resource_id = str(row.get("resource_id", ""))
        instance_type = str(row.get("instance_type", ""))
        pricing_model = str(row.get("pricing_model", "OnDemand"))
        is_blocked = str(row.get("safety_tier", "")) == "HARD_BLOCK"
        is_spot_eligible = bool(row.get("is_spot_eligible", False))
        cost_90d = float(row.get("total_cost_90d", 0) or 0)

        if is_blocked:
            return {
                "found": True,
                "resource_name": resource_name,
                "resource_id": resource_id,
                "instance_type": instance_type,
                "pricing_model": pricing_model,
                "is_blocked": True,
                "is_spot_eligible": False,
                "note": f"🔒 HARD BLOCKED — {resource_name} is permanently protected. Spot conversion cannot be applied.",
            }

        monthly = round(cost_90d / PILOT_DAYS * 30, 2)
        spot_90d = round(cost_90d * (1 - SPOT_SAVING_PCT / 100), 2)
        spot_monthly = round(spot_90d / PILOT_DAYS * 30, 2)
        missed_90d = round(cost_90d - spot_90d, 2)
        missed_monthly = round(monthly - spot_monthly, 2)
        annual = round(missed_90d * (365 / PILOT_DAYS), 2)

        eligibility_note = ""
        if pricing_model.lower() == "spot":
            eligibility_note = " (already on Spot)"
        elif not is_spot_eligible:
            eligibility_note = " (not Spot-eligible — may be production or EKS node)"

        note = (
            f"{resource_name} ({instance_type}) costs ${monthly}/month on {pricing_model}{eligibility_note}. "
            f"If on Spot for the full 89-day pilot: ${spot_monthly}/month — saving ${missed_monthly}/month "
            f"(${missed_90d} over 89 days, ${annual}/year projected)."
        )

        return {
            "found": True,
            "resource_name": resource_name,
            "resource_id": resource_id,
            "instance_type": instance_type,
            "pricing_model": pricing_model,
            "is_blocked": False,
            "is_spot_eligible": is_spot_eligible,
            "ondemand_cost_90d": cost_90d,
            "ondemand_monthly": monthly,
            "spot_cost_90d": spot_90d,
            "spot_monthly": spot_monthly,
            "missed_saving_90d": missed_90d,
            "missed_saving_monthly": missed_monthly,
            "annual_projection": annual,
            "saving_pct": SPOT_SAVING_PCT,
            "note": note,
        }

    def fleet_summary(self) -> dict:
        """Overall Spot savings potential across entire fleet."""
        if not os.path.exists(PARQUET_PATH):
            return {"error": "No fleet data available."}
        try:
            df = pd.read_parquet(PARQUET_PATH)
        except Exception as e:
            return {"error": f"Could not read fleet data: {e}"}

        eligible = df[df["is_spot_eligible"] == True]
        total_cost_90d = float(eligible["total_cost_90d"].fillna(0).sum())
        monthly_cost = round(total_cost_90d / PILOT_DAYS * 30, 2)
        spot_monthly = round(monthly_cost * (1 - SPOT_SAVING_PCT / 100), 2)
        saving_monthly = round(monthly_cost - spot_monthly, 2)

        return {
            "eligible_count": len(eligible),
            "eligible_monthly_cost": monthly_cost,
            "spot_monthly_cost": spot_monthly,
            "saving_monthly": saving_monthly,
            "saving_pct": SPOT_SAVING_PCT,
            "note": f"{len(eligible)} eligible instances -> ${saving_monthly}/month saving at {SPOT_SAVING_PCT}% Spot discount.",
        }
