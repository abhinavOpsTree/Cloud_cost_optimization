"""
services/cost_anomaly_service.py
---------------------------------
Cost Anomaly Detection Service.

Reads ALL billing rows (not just EC2 — all product types).
Groups by date. Calculates rolling 7-day average.
Flags dates where actual > average × 1.3 (spike_multiplier from config).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List

import pandas as pd


class CostAnomalyService:
    """Detects cost spikes across all product types."""

    SPIKE_MULTIPLIER = 1.3

    def __init__(self, data_path: str = None):
# Data loaded live via UnitEconPro API
        self.data_path = data_path

    def detect_anomalies(self) -> List[Dict]:
        """
        Detect cost anomalies using rolling 7-day average.

        Returns list of anomaly dicts:
        [{"date": str, "actual_cost": float, "average_cost": float,
          "spike_pct": float, "top_instances": list}]
        """
        # The file existence check is no longer strictly necessary, but we can leave it or remove it.
        # It's better to just read from config.

        try:
            import yaml
            from core.live_data_loader import get_live_billing_df
            with open("config.yaml", "r") as f:
                config = yaml.safe_load(f)
            tracked_instances = config.get("data", {}).get("tracked_instances", [])
            df = get_live_billing_df(tracked_instances)
        except Exception as e:
            print(f"[Anomaly] Failed to read Excel: {e}")
            return []

        # Find the cost column
        cost_col = None
        for col in df.columns:
            if "cost" in str(col).lower() and "blend" in str(col).lower():
                cost_col = col
                break
        if not cost_col:
            for col in df.columns:
                if "cost" in str(col).lower():
                    cost_col = col
                    break
        if not cost_col:
            return []

        # Find date column
        date_col = None
        for col in df.columns:
            if "start" in str(col).lower() and ("date" in str(col).lower() or "time" in str(col).lower()):
                date_col = col
                break
        if not date_col:
            return []

        df[cost_col] = pd.to_numeric(df[cost_col], errors="coerce").fillna(0)
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])

        # Group by date
        daily = df.groupby(df[date_col].dt.date).agg(
            actual_cost=(cost_col, "sum"),
        ).reset_index()
        daily.columns = ["date", "actual_cost"]
        daily = daily.sort_values("date")

        # Rolling 7-day average
        daily["avg_7d"] = daily["actual_cost"].rolling(window=7, min_periods=1).mean()
        daily["threshold"] = daily["avg_7d"] * self.SPIKE_MULTIPLIER

        anomalies = []
        for _, row in daily.iterrows():
            if row["actual_cost"] > row["threshold"] and row["avg_7d"] > 0:
                spike_pct = ((row["actual_cost"] - row["avg_7d"]) / row["avg_7d"]) * 100

                # Find top instances for this date
                date_rows = df[df[date_col].dt.date == row["date"]]
                top = date_rows.nlargest(3, cost_col)
                top_instances = []
                for _, t in top.iterrows():
                    name = t.get("resource_name", "") or t.get("lineItem/ResourceId", "")
                    top_instances.append({
                        "name": str(name),
                        "cost": round(float(t[cost_col]), 2),
                    })

                anomalies.append({
                    "date": str(row["date"]),
                    "actual_cost": round(row["actual_cost"], 2),
                    "average_cost": round(row["avg_7d"], 2),
                    "spike_pct": round(spike_pct, 1),
                    "top_instances": top_instances,
                })

        return anomalies
