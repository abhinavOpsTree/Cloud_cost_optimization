"""
agents/finops_chat_agent.py
----------------------------
FinOps Chat Agent — fleet-aware chatbot with memory and streaming.

This IS an AI Agent (uses Gemini for every response).

System prompt: fleet context from all context skills combined.
Memory: loads last 10 messages from conversations table at session start.
Every message saved to conversations table immediately.
Streaming response via SSE (in API layer — this agent returns full text).

Must answer these questions correctly with real numbers:
  - "Which instance costs the most?" → VPN server $87.54 / $29.18 per month
  - "How much would Spot save?" → 94 instances, $73.36/month
  - "What drives NAT costs?" → EKS clusters, $118.96/month
  - "How many untagged instances?" → 237 with no meaningful tags
  - "Why was VPN server blocked?" → "do no delete" in name, Tier 1 hard block
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from core.state_store import StateStore
from core.llm_client import call_gemini
from skills.context.ec2_fleet_context import EC2FleetContextSkill
from skills.context.nat_gateway_context import NATGatewayContextSkill
from skills.context.savings_context import SavingsContextSkill


class FinOpsChatAgent:
    """
    Fleet-aware FinOps chatbot with conversation memory.

    Usage:
        chat = FinOpsChatAgent()
        response = chat.chat("Which instance costs the most?", "session-1")
    """

    def __init__(self):
        self.store = StateStore()
        self.context_skills = [
            EC2FleetContextSkill(),
            NATGatewayContextSkill(),
            SavingsContextSkill(),
        ]
        self._system_prompt = None

    def _build_fleet_stats(self) -> dict:
        """Build live fleet stats from parquet and StateStore. Cached for 60s."""
        import os, time
        import pandas as pd

        # Simple TTL cache
        now = time.time()
        if hasattr(self, '_stats_cache') and (now - self._stats_cache_time) < 60:
            return self._stats_cache

        stats = {
            "total_instances": 0,
            "total_monthly_cost": 0.0,
            "most_expensive_name": "Unknown",
            "most_expensive_cost": 0.0,
            "spot_eligible_count": 0,
            "spot_savings": 0.0,
            "eks_node_count": 0,
            "hard_blocked_count": 0,
            "instances_with_cpu": 0,
            "instances_without_tags": 0,
            "nat_monthly": 0.0,
            "regions": [],
            "instance_types": {},
        }

        if os.path.exists("cache/enriched_instances.parquet"):
            df = pd.read_parquet("cache/enriched_instances.parquet")
            if not df.empty:
                stats["total_instances"] = len(df)
                if "monthly_cost_est" in df.columns:
                    stats["total_monthly_cost"] = round(float(df["monthly_cost_est"].sum()), 2)
                    most_expensive = df.loc[df["monthly_cost_est"].idxmax()]
                    stats["most_expensive_name"] = str(most_expensive.get("resource_name", "") or most_expensive.get("resource_id", ""))
                    stats["most_expensive_cost"] = round(float(most_expensive["monthly_cost_est"]), 2)
                if "is_spot_eligible" in df.columns:
                    spot_df = df[df["is_spot_eligible"] == True]
                    stats["spot_eligible_count"] = len(spot_df)
                    if "monthly_cost_est" in spot_df.columns:
                        stats["spot_savings"] = round(float(spot_df["monthly_cost_est"].sum()) * 0.65, 2)
                if "cluster_name" in df.columns:
                    stats["eks_node_count"] = int(df["cluster_name"].notna().sum())
                if "safety_tier" in df.columns:
                    stats["hard_blocked_count"] = int((df["safety_tier"] == "HARD_BLOCK").sum())
                if "cpu_avg_pct" in df.columns:
                    stats["instances_with_cpu"] = int(df["cpu_avg_pct"].notna().sum())
                if "all_tags" in df.columns:
                    def _has_meaningful_tags(t):
                        try:
                            if not t or t in ('{}', 'nan', 'None', ''): return False
                            d = eval(str(t)) if isinstance(t, str) else t
                            return isinstance(d, dict) and len(d) > 0
                        except: return False
                    stats["instances_without_tags"] = int((~df["all_tags"].apply(_has_meaningful_tags)).sum())
                if "region" in df.columns:
                    stats["regions"] = list(df["region"].dropna().unique())
                if "instance_type" in df.columns:
                    stats["instance_types"] = df["instance_type"].value_counts().head(10).to_dict()

        if os.path.exists("cache/nat_gateway_data.parquet"):
            df_nat = pd.read_parquet("cache/nat_gateway_data.parquet")
            if not df_nat.empty:
                stats["nat_monthly"] = round(float(df_nat["cost_90d"].sum()) / 3, 2)

        # Recommendation stats from DB
        recs = self.store.get_all_recommendations()
        stats["total_recs"] = len(recs)
        stats["approved_recs"] = sum(1 for r in recs if r.get("status") == "APPROVED")
        stats["blocked_recs"] = sum(1 for r in recs if r.get("status") == "BLOCKED")
        stats["flagged_recs"] = sum(1 for r in recs if r.get("status") == "FLAGGED")
        stats["total_identified_savings"] = round(sum(r.get("estimated_monthly_saving", 0) or 0 for r in recs), 2)

        self._stats_cache = stats
        self._stats_cache_time = now
        return stats

    def _get_time_context(self, message: str) -> str:
        """Detect time references in message and fetch live cost data for that period."""
        import re
        from datetime import datetime, timedelta

        message_lower = message.lower()
        start_date = None
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        label = None

        # Detect time patterns
        if "last week" in message_lower or "past week" in message_lower or "last 7 days" in message_lower:
            start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
            label = "Last 7 days"
        elif "last month" in message_lower or "past month" in message_lower or "last 30 days" in message_lower:
            start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
            label = "Last 30 days"
        elif "last 90 days" in message_lower or "last quarter" in message_lower or "past 3 months" in message_lower:
            start_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            label = "Last 90 days"
        elif "last 6 months" in message_lower or "past 6 months" in message_lower:
            start_date = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
            label = "Last 6 months"
        elif "last year" in message_lower or "past year" in message_lower or "last 365 days" in message_lower:
            start_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
            label = "Last year"
        elif "this month" in message_lower:
            now = datetime.utcnow()
            start_date = now.replace(day=1).strftime("%Y-%m-%d")
            label = "This month so far"

        # Try to detect month names (e.g., "in June", "in May 2026")
        month_match = re.search(r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b', message_lower)
        if month_match and not label:
            month_name = month_match.group(1)
            month_num = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
                         "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}[month_name]
            year_match = re.search(r'\b(202[0-9])\b', message)
            year = int(year_match.group(1)) if year_match else datetime.utcnow().year
            import calendar
            _, last_day = calendar.monthrange(year, month_num)
            start_date = f"{year}-{month_num:02d}-01"
            end_date = f"{year}-{month_num:02d}-{last_day:02d}"
            label = f"{month_name.capitalize()} {year}"

        if not start_date:
            return ""

        # Fetch live cost data for this time period
        try:
            from core.uniteconpro_client import get_ec2_summary
            summary = get_ec2_summary(account="opstree", start_date=start_date, end_date=end_date)
            if summary:
                cost = summary.get("total_cost", 0.0)
                instances = summary.get("total_instances", 0)
                return f"\n\nTIME-SPECIFIC DATA ({label}, {start_date} to {end_date}):\n- Total EC2 cost: ${cost:.2f}\n- Active instances in period: {instances}\nUse these EXACT numbers when answering about this time period."
        except Exception as e:
            print(f"[CHAT] Time-aware query failed: {e}")

        return ""

    def _build_system_prompt(self) -> str:
        """Build system prompt dynamically from live fleet data."""
        if self._system_prompt:
            return self._system_prompt

        context_parts = []
        for skill in self.context_skills:
            try:
                ctx = skill.load_context()
                if ctx:
                    context_parts.append(ctx)
            except Exception as e:
                print(f"[CHAT] Context skill {skill.NAME} failed: {e}")

        # Add governance context
        try:
            decisions = self.store.get_all_governance_decisions()
            blocked = [d for d in decisions if d.get("decision") == "BLOCKED"]
            if blocked:
                gov_lines = ["GOVERNANCE DECISIONS:"]
                for d in blocked:
                    gov_lines.append(
                        f"  - {d.get('resource_name', '')}: BLOCKED (Tier {d.get('tier')}) — {d.get('reason', '')}"
                    )
                context_parts.append("\n".join(gov_lines))
        except Exception:
            pass

        fleet_context = "\n\n---\n\n".join(context_parts)

        # Build dynamic stats
        s = self._build_fleet_stats()

        self._system_prompt = f"""You are Cloud-Sentry AI, an intelligent FinOps assistant for OpsTree Solutions.
You have complete knowledge of the AWS fleet loaded from UnitEconPro.

LIVE FLEET DATA (dynamically computed — always use these exact numbers):
- Total EC2 instances analyzed: {s['total_instances']}
- Monthly EC2 run rate: ${s['total_monthly_cost']}
- Most expensive instance: {s['most_expensive_name']} (${s['most_expensive_cost']}/month)
- Spot-eligible instances: {s['spot_eligible_count']}, potential saving: ~${s['spot_savings']}/month (65% of their combined cost)
- NAT Gateway monthly cost: ${s['nat_monthly']} (driven by EKS clusters pulling container images)
- EKS nodes: {s['eks_node_count']}
- Hard-blocked instances: {s['hard_blocked_count']} (have "do not/no delete" in name)
- Instances with CloudWatch CPU data: {s['instances_with_cpu']}
- Instances without meaningful tags: {s['instances_without_tags']}
- Total recommendations: {s['total_recs']} (Approved: {s['approved_recs']}, Blocked: {s['blocked_recs']}, Flagged: {s['flagged_recs']})
- Total identified savings: ${s['total_identified_savings']}/month
- Active regions: {', '.join(s['regions']) if s['regions'] else 'ap-south-1'}

FLEET CONTEXT:
{fleet_context}

RULES:
1. Always use real numbers from the LIVE FLEET DATA above — never guess or approximate
2. When asked about a specific instance, use its exact name and metrics
3. When asked about savings, cite the exact number of eligible instances and dollar amounts
4. Explain governance decisions by tier (Tier 1 = hard block, Tier 2 = flag, Tier 3 = AI review)
5. Be concise but specific. Use rich markdown formatting (bold text, bullet points). When presenting structured data, ALWAYS use markdown tables.
6. If the user asks for charts, graphs, or visualizations, you MUST use mermaid.js syntax (e.g. pie chart, flowchart).
CRITICAL: Mermaid charts have known rendering bugs when plotting data with extreme variance. For high-variance data, use a clean text bar chart inside a code block.
IMPORTANT: Do NOT explain chart format choices to the user. Just output the chart seamlessly.
7. If the user asks about a SPECIFIC TIME PERIOD (last week, last month, June, etc.), use the TIME-SPECIFIC DATA provided below these rules. If no time-specific data is provided, use the current fleet data.
8. If you don't know something, say so — don't make up data."""

        return self._system_prompt

    def chat(self, message: str, session_id: str) -> str:
        """
        Process a chat message and return the response.

        Args:
            message: User's question
            session_id: Conversation session ID

        Returns:
            Assistant response text
        """
        # Save user message immediately
        self.store.save_message(session_id, "user", message)

        # Load conversation history (last 10 messages)
        history = self.store.get_conversation_history(session_id, limit=10)

        # Reset system prompt cache to ensure fresh data on each call
        self._system_prompt = None

        # Build conversation context
        system_prompt = self._build_system_prompt()
        
        # Add time-specific context if the user asks about a time period
        time_context = self._get_time_context(message)
        
        conversation = ""
        for msg in history[:-1]:  # exclude the just-saved message
            role = msg.get("role", "user")
            text = msg.get("message", "")
            conversation += f"\n{role.upper()}: {text}"

        prompt = f"""{system_prompt}{time_context}

CONVERSATION HISTORY:
{conversation}

USER: {message}

Respond as Cloud-Sentry AI. Be helpful, specific, and use real numbers from the fleet data."""

        # --- DETERMINISTIC INTENT ROUTING (no Gemini cost) ---
        # Check for script generation intent FIRST before calling Gemini
        script_intent_keywords = [
            "generate script", "generate scripts", "terraform for", "cli for",
            "optimize ", "optimise ", "remediate ", "scripts for",
            "aws cli command", "what commands", "how do i fix"
        ]
        message_lower = message.lower()

        if any(kw in message_lower for kw in script_intent_keywords):
            try:
                from services.chatbot_script_service import ChatbotScriptService
                svc = ChatbotScriptService()
                result = svc.generate_for_instance(message)
                response = result.get("chat_message", "Could not generate scripts for that instance.")
                response_source = "deterministic"
            except Exception as e:
                print(f"[CHAT] Script generation failed, falling back to Gemini: {e}")
                # Fall through to Gemini below
                response = None
                response_source = "gemini"
        else:
            response = None
            response_source = "gemini"

        # Fleet query intent (deterministic, no Gemini)
        fleet_query_keywords = [
            "show all", "list all", "how many", "total cost by", "cost by region",
            "by environment", "group by", "filter by", "all c5", "all m5", "all t3",
            "all eks", "all spot", "all ondemand", "instances over $", "instances under $"
        ]
        if response is None and any(kw in message_lower for kw in fleet_query_keywords):
            try:
                from services.fleet_query_service import FleetQueryService
                svc = FleetQueryService()
                # Simple heuristic routing
                filters = {}
                group_by = ""
                if "by region" in message_lower: group_by = "region"
                elif "by environment" in message_lower or "by env" in message_lower: group_by = "env"
                elif "by pricing" in message_lower or "spot vs" in message_lower: group_by = "pricing_model"
                elif "c5" in message_lower: filters["instance_family"] = "c5"
                elif "m5" in message_lower: filters["instance_family"] = "m5"
                elif "t3" in message_lower: filters["instance_family"] = "t3"
                if "eks" in message_lower or "kubernetes" in message_lower: filters["is_eks"] = True
                if "spot" in message_lower and "ondemand" not in message_lower: filters["pricing_model"] = "Spot"
                if "ondemand" in message_lower or "on demand" in message_lower: filters["pricing_model"] = "OnDemand"
                result = svc.query(filters=filters, group_by=group_by, top_n=15)
                if "error" not in result:
                    if result.get("grouped"):
                        lines = [f"📊 **Fleet breakdown by {group_by}** ({result['total_matched']} instances, ${result['total_monthly_cost']}/month total)\n"]
                        for row in result["grouped"]:
                            lines.append(f"- **{row['group']}**: {int(row['count'])} instances — ${row['monthly_cost']:.2f}/month")
                        response = "\n".join(lines)
                        response_source = "deterministic"
                    elif result.get("rows"):
                        lines = [f"📋 **{result['total_matched']} instances matched** (${result['total_monthly_cost']}/month total)\n"]
                        for row in result["rows"][:10]:
                            cpu_str = f"{row['cpu_p95']}% CPU p95" if row.get('cpu_p95') else "No CPU data"
                            lines.append(f"- **{row['resource_name']}** ({row['instance_type']}) — ${row['monthly_cost']}/month | {cpu_str} | {row['env']}")
                        response = "\n".join(lines)
                        response_source = "deterministic"
            except Exception as e:
                print(f"[CHAT] Fleet query routing failed, falling back to Gemini: {e}")

        # Spot what-if intent (deterministic, no Gemini)
        spot_keywords = ["spot saving", "spot savings", "what if spot", "if on spot", "spot for "]
        if response is None and any(kw in message_lower for kw in spot_keywords):
            try:
                from services.spot_simulator import SpotSimulator
                # Extract instance name from message (simple heuristic)
                import re
                words = message.split()
                search_term = next((w for w in reversed(words) if len(w) > 3 and w.lower() not in
                                   {"spot", "saving", "savings", "what", "would", "save", "conversion", "for", "the"}), "")
                if search_term:
                    sim = SpotSimulator()
                    result = sim.simulate(search_term)
                    if result.get("found"):
                        response = f"💰 **Spot What-If: {result['resource_name']}**\n\n{result['note']}"
                        if result.get("is_blocked"):
                            response = f"🔒 {result['note']}"
                        response_source = "deterministic"
                else:
                    sim = SpotSimulator()
                    fleet = sim.fleet_summary()
                    response = f"💰 **Fleet Spot Savings Potential**\n\n{fleet.get('note', '')}"
                    response_source = "deterministic"
            except Exception as e:
                print(f"[CHAT] Spot routing failed, falling back to Gemini: {e}")

        # Call Gemini only if deterministic routing did not produce a response
        if response is None:
            response = call_gemini(
                prompt=prompt,
                agent="finops_chat",
                resource_id=session_id,
            )
            response_source = "gemini"

        # Save assistant response immediately
        self.store.save_message(session_id, "assistant", response)

        return response
