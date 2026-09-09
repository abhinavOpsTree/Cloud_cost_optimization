"""
core/state_store.py
-------------------
SQLite wrapper for all Cloud-Sentry AI state.

Creates all 11 tables on first init.
Provides CRUD methods used by every agent.
Never raises unhandled exceptions — all DB errors are caught and logged.

Tables:
    recommendations         — FinOps Analyst Agent output
    remediations            — DevOps Remediation Agent output (permanent audit trail)
    conversations           — FinOps Chat Agent message history
    conversation_sessions   — Chat session metadata and summaries
    governance_decisions    — Governance Agent decisions + Tier 3 Gemini cache
    llm_usage               — Every Gemini API call logged
    ingest_runs             — Fleet Intelligence Processor run history
    skill_results           — Per-skill per-instance execution results
    analysis_runs           — Full analysis run records
    skill_submissions       — User-submitted skill ideas for admin review
    skill_admins            — Allowed admin emails for skill review
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


DB_PATH = "state/remediation.db"


class StateStore:
    """SQLite wrapper. Thread-safe for single-process use (pilot)."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.create_tables()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a write statement. Swallows errors and logs to console."""
        try:
            with self._conn() as conn:
                conn.execute(sql, params)
        except Exception as e:
            print(f"[StateStore] DB write error: {e}")

    def _fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Execute a read and return list of dicts."""
        try:
            with self._conn() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"[StateStore] DB read error: {e}")
            return []

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """Execute a read and return a single dict or None."""
        try:
            with self._conn() as conn:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None
        except Exception as e:
            print(f"[StateStore] DB read error: {e}")
            return None

    # ------------------------------------------------------------------
    # Table creation (idempotent)
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        """Create all 9 tables. Safe to call multiple times (IF NOT EXISTS)."""
        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                resource_name TEXT,
                instance_type TEXT,
                region TEXT,
                track TEXT,
                action TEXT,
                current_monthly_cost REAL,
                estimated_monthly_saving REAL,
                saving_pct REAL,
                confidence REAL,
                rationale TEXT,
                status TEXT DEFAULT 'PENDING_REVIEW',
                gate_tier INTEGER,
                gate_reason TEXT,
                has_performance_data INTEGER DEFAULT 0,
                skill_name TEXT,
                created_at TEXT,
                executed_at TEXT,
                confidence_reasons TEXT DEFAULT '[]'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS remediations (
                id TEXT PRIMARY KEY,
                recommendation_id TEXT,
                resource_id TEXT NOT NULL,
                resource_name TEXT,
                action_taken TEXT,
                terraform_hcl TEXT,
                aws_cli_command TEXT,
                rollback_command TEXT,
                eventbridge_rule TEXT,
                executed_by TEXT DEFAULT 'engineer',
                executed_at TEXT,
                realized_saving REAL,
                status TEXT DEFAULT 'EXECUTED'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                resource_mentioned TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT,
                ended_at TEXT,
                summary TEXT,
                message_count INTEGER DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS governance_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id TEXT NOT NULL,
                resource_name TEXT,
                decision TEXT,
                tier INTEGER,
                reason TEXT,
                gemini_assessment TEXT,
                assessed_at TEXT,
                human_override INTEGER DEFAULT 0,
                human_override_reason TEXT,
                run_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                agent TEXT,
                resource_id TEXT,
                model TEXT DEFAULT 'gemini-3.5-flash',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                called_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                source_file TEXT,
                source_file_size INTEGER,
                instances_found INTEGER,
                eks_nodes_found INTEGER,
                hard_blocked_found INTEGER,
                spot_eligible_found INTEGER,
                gemini_calls_used INTEGER DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                status TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                skill_name TEXT,
                resource_id TEXT,
                applied INTEGER DEFAULT 0,
                finding TEXT,
                recommendation_generated INTEGER DEFAULT 0,
                execution_time_ms INTEGER,
                ran_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT,
                completed_at TEXT,
                instances_analysed INTEGER,
                recommendations_generated INTEGER,
                blocked_count INTEGER DEFAULT 0,
                flagged_count INTEGER DEFAULT 0,
                approved_count INTEGER DEFAULT 0,
                gemini_calls_total INTEGER DEFAULT 0,
                estimated_gemini_cost_usd REAL DEFAULT 0.0,
                fleet_summary TEXT,
                status TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_submissions (
                id TEXT PRIMARY KEY,
                skill_name TEXT NOT NULL,
                description TEXT NOT NULL,
                track TEXT NOT NULL,
                code_content TEXT NOT NULL,
                submitted_by TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT,
                review_notes TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_admins (
                email TEXT PRIMARY KEY,
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
            """,
        ]
        try:
            with self._conn() as conn:
                for ddl in ddl_statements:
                    conn.execute(ddl)
        except Exception as e:
            print(f"[StateStore] Table creation error: {e}")
            raise

    # ------------------------------------------------------------------
    # Analysis runs
    # ------------------------------------------------------------------

    def start_analysis_run(self) -> str:
        """Create a new analysis run record. Returns the run_id."""
        run_id = str(uuid.uuid4())
        self._execute(
            "INSERT INTO analysis_runs (run_id, started_at, status) VALUES (?, ?, ?)",
            (run_id, datetime.utcnow().isoformat(), "RUNNING"),
        )
        return run_id

    def complete_analysis_run(self, run_id: str, stats: Dict) -> None:
        """Update analysis run with final stats."""
        self._execute(
            """UPDATE analysis_runs SET
               completed_at=?, instances_analysed=?, recommendations_generated=?,
               blocked_count=?, flagged_count=?, approved_count=?,
               gemini_calls_total=?, estimated_gemini_cost_usd=?,
               fleet_summary=?, status=?
               WHERE run_id=?""",
            (
                datetime.utcnow().isoformat(),
                stats.get("instances_analysed", 0),
                stats.get("recommendations_generated", 0),
                stats.get("blocked_count", 0),
                stats.get("flagged_count", 0),
                stats.get("approved_count", 0),
                stats.get("gemini_calls_total", 0),
                stats.get("estimated_gemini_cost_usd", 0.0),
                stats.get("fleet_summary", ""),
                "COMPLETED",
                run_id,
            ),
        )

    def clear_unexecuted_recommendations(self) -> None:
        """Clear all recommendations that have not been executed."""
        self._execute("DELETE FROM recommendations WHERE status != 'EXECUTED'")

    def get_analysis_runs(self, limit: int = 10) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def save_recommendation(self, rec: Dict) -> None:
        """Insert or replace a recommendation."""
        # Generate deterministic ID to prevent duplicates across multiple runs
        rec_id = rec.get("id")
        if not rec_id:
            rec_id = f"rec-{rec['resource_id']}-{rec.get('track', 'unknown')}"
            
        self._execute(
            """INSERT OR REPLACE INTO recommendations
               (id, resource_id, resource_name, instance_type, region, track, action,
                current_monthly_cost, estimated_monthly_saving, saving_pct, confidence,
                rationale, status, gate_tier, gate_reason, has_performance_data,
                skill_name, created_at, executed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec_id,
                rec["resource_id"],
                rec.get("resource_name", ""),
                rec.get("instance_type", ""),
                rec.get("region", ""),
                rec.get("track", ""),
                rec.get("action", ""),
                rec.get("current_monthly_cost", 0.0),
                rec.get("estimated_monthly_saving", 0.0),
                rec.get("saving_pct", 0.0),
                rec.get("confidence", 0.0),
                rec.get("rationale", ""),
                rec.get("status", "PENDING_REVIEW"),
                rec.get("gate_tier"),
                rec.get("gate_reason"),
                1 if rec.get("has_performance_data") else 0,
                rec.get("skill_name", ""),
                rec.get("created_at", datetime.utcnow().isoformat()),
                rec.get("executed_at"),
            ),
        )

    def get_all_recommendations(
        self,
        status: Optional[str] = None,
        track: Optional[str] = None,
    ) -> List[Dict]:
        """Return all recommendations, optionally filtered."""
        sql = "SELECT * FROM recommendations WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if track:
            sql += " AND track=?"
            params.append(track)
        sql += " ORDER BY estimated_monthly_saving DESC"
        rows = self._fetchall(sql, tuple(params))
        # Convert has_performance_data int back to bool
        for r in rows:
            r["has_performance_data"] = bool(r.get("has_performance_data", 0))
        return rows

    def get_recommendation(self, rec_id: str) -> Optional[Dict]:
        row = self._fetchone("SELECT * FROM recommendations WHERE id=?", (rec_id,))
        if row:
            row["has_performance_data"] = bool(row.get("has_performance_data", 0))
        return row

    def update_recommendation_status(
        self,
        rec_id: str,
        status: str,
        gate_tier: Optional[int] = None,
        gate_reason: Optional[str] = None,
    ) -> None:
        self._execute(
            "UPDATE recommendations SET status=?, gate_tier=?, gate_reason=? WHERE id=?",
            (status, gate_tier, gate_reason, rec_id),
        )

    def mark_recommendation_executed(self, rec_id: str) -> None:
        self._execute(
            "UPDATE recommendations SET status='REMEDIATED', executed_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), rec_id),
        )

    # ------------------------------------------------------------------
    # Remediations
    # ------------------------------------------------------------------

    def save_remediation(self, rem: Dict) -> str:
        """Store a generated/executed remediation. Returns remediation id."""
        rem_id = rem.get("id", str(uuid.uuid4()))
        self._execute(
            """INSERT OR REPLACE INTO remediations
               (id, recommendation_id, resource_id, resource_name, action_taken,
                terraform_hcl, aws_cli_command, rollback_command, eventbridge_rule,
                executed_by, executed_at, realized_saving, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rem_id,
                rem.get("recommendation_id", ""),
                rem["resource_id"],
                rem.get("resource_name", ""),
                rem.get("action_taken", ""),
                rem.get("terraform_hcl", ""),
                rem.get("aws_cli_command", ""),
                rem.get("rollback_command", ""),
                rem.get("eventbridge_rule"),
                rem.get("executed_by", "engineer"),
                rem.get("executed_at"),
                rem.get("realized_saving"),
                rem.get("status", "GENERATED"),
            ),
        )
        return rem_id

    def get_remediation_by_resource(self, resource_id: str) -> Optional[Dict]:
        """Get the most recent remediation for a resource_id."""
        return self._fetchone(
            "SELECT * FROM remediations WHERE resource_id=? ORDER BY executed_at DESC LIMIT 1",
            (resource_id,),
        )

    def get_all_remediations(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM remediations ORDER BY executed_at DESC")

    def get_savings_summary(self) -> Dict:
        """Calculate savings summary from remediations table."""
        executed = self._fetchall(
            "SELECT * FROM remediations WHERE status='EXECUTED'"
        )
        realized = sum(r.get("realized_saving") or 0.0 for r in executed)
        identified = sum(
            (r.get("estimated_monthly_saving") or 0.0)
            for r in self.get_all_recommendations()
        )
        return {
            "total_identified": round(identified, 2),
            "realized_savings": round(realized, 2),
            "total_remediations": len(executed),
            "by_status": {},
        }

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def save_message(
        self,
        session_id: str,
        role: str,
        message: str,
        resource_mentioned: Optional[str] = None,
    ) -> None:
        """Save a chat message immediately."""
        self._execute(
            """INSERT INTO conversations
               (session_id, role, message, timestamp, resource_mentioned)
               VALUES (?,?,?,?,?)""",
            (session_id, role, message, datetime.utcnow().isoformat(), resource_mentioned),
        )
        # Update session message count
        self._execute(
            """INSERT INTO conversation_sessions (session_id, started_at, message_count)
               VALUES (?, ?, 1)
               ON CONFLICT(session_id) DO UPDATE SET
               message_count = message_count + 1""",
            (session_id, datetime.utcnow().isoformat()),
        )

    def get_conversation_history(
        self, session_id: str, limit: int = 10
    ) -> List[Dict]:
        """Return last N messages for a session, oldest first."""
        rows = self._fetchall(
            """SELECT * FROM (
               SELECT * FROM conversations WHERE session_id=?
               ORDER BY timestamp DESC LIMIT ?
               ) ORDER BY timestamp ASC""",
            (session_id, limit),
        )
        return rows

    def save_session_summary(self, session_id: str, summary: str) -> None:
        self._execute(
            """UPDATE conversation_sessions SET summary=?, ended_at=?
               WHERE session_id=?""",
            (summary, datetime.utcnow().isoformat(), session_id),
        )

    # ------------------------------------------------------------------
    # Governance decisions
    # ------------------------------------------------------------------

    def save_governance_decision(self, decision: Dict) -> None:
        """Save a governance decision. Used for both audit and Tier 3 caching."""
        self._execute(
            """INSERT INTO governance_decisions
               (resource_id, resource_name, decision, tier, reason,
                gemini_assessment, assessed_at, human_override,
                human_override_reason, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                decision["resource_id"],
                decision.get("resource_name", ""),
                decision["decision"],
                decision.get("tier"),
                decision.get("reason", ""),
                json.dumps(decision.get("gemini_assessment")) if decision.get("gemini_assessment") else None,
                decision.get("assessed_at", datetime.utcnow().isoformat()),
                1 if decision.get("human_override") else 0,
                decision.get("human_override_reason"),
                decision.get("run_id"),
            ),
        )

    def get_governance_decision(self, resource_id: str) -> Optional[Dict]:
        """Get the most recent governance decision for a resource."""
        return self._fetchone(
            """SELECT * FROM governance_decisions WHERE resource_id=?
               ORDER BY assessed_at DESC LIMIT 1""",
            (resource_id,),
        )

    def get_cached_governance_decision(
        self, resource_id: str, cache_days: int = 7
    ) -> Optional[Dict]:
        """
        Return a Tier 3 Gemini decision if cached within cache_days.
        Returns None if no valid cache exists (caller must call Gemini).
        """
        row = self.get_governance_decision(resource_id)
        if not row:
            return None
        if row.get("tier") != 3:
            return None  # only cache Tier 3 Gemini assessments
        try:
            assessed = datetime.fromisoformat(row["assessed_at"])
            if datetime.utcnow() - assessed < timedelta(days=cache_days):
                if row.get("gemini_assessment"):
                    row["gemini_assessment"] = json.loads(row["gemini_assessment"])
                return row
        except Exception:
            pass
        return None

    def get_all_governance_decisions(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT g.*, (SELECT resource_name FROM recommendations r WHERE r.resource_id = g.resource_id LIMIT 1) as resource_name
            FROM governance_decisions g
            ORDER BY g.assessed_at DESC
            """
        )

    # ------------------------------------------------------------------
    # LLM usage tracking
    # ------------------------------------------------------------------

    def log_llm_usage(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        resource_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Log a single Gemini API call. Called by llm_client after every call."""
        # Approximate cost: $0.075 per 1M input tokens, $0.30 per 1M output
        # (gemini-3.5-flash approximate pricing)
        cost = (input_tokens * 0.075 + output_tokens * 0.30) / 1_000_000
        self._execute(
            """INSERT INTO llm_usage
               (run_id, agent, resource_id, model, input_tokens, output_tokens,
                estimated_cost_usd, called_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                run_id,
                agent,
                resource_id,
                model,
                input_tokens,
                output_tokens,
                round(cost, 6),
                datetime.utcnow().isoformat(),
            ),
        )

    def get_llm_usage_summary(self) -> Dict:
        """Aggregate LLM usage across all calls."""
        rows = self._fetchall("SELECT * FROM llm_usage")
        if not rows:
            return {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "by_agent": {},
            }
        total_calls = len(rows)
        total_in = sum(r.get("input_tokens", 0) for r in rows)
        total_out = sum(r.get("output_tokens", 0) for r in rows)
        total_cost = sum(r.get("estimated_cost_usd", 0.0) for r in rows)
        by_agent: Dict[str, int] = {}
        for r in rows:
            a = r.get("agent", "unknown")
            by_agent[a] = by_agent.get(a, 0) + 1
        return {
            "total_calls": total_calls,
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "estimated_cost_usd": round(total_cost, 6),
            "by_agent": by_agent,
        }

    def get_llm_usage_current_run(self) -> Dict:
        """Return usage for the most recent analysis run."""
        rows = self._fetchall(
            """SELECT lu.* FROM llm_usage lu
               INNER JOIN (SELECT run_id FROM analysis_runs ORDER BY started_at DESC LIMIT 1) ar
               ON lu.run_id = ar.run_id"""
        )
        if not rows:
            # Fallback: all usage
            return self.get_llm_usage_summary()
        total_calls = len(rows)
        total_tokens = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows)
        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(
                sum(r.get("estimated_cost_usd", 0.0) for r in rows), 6
            ),
        }

    # ------------------------------------------------------------------
    # Ingest runs
    # ------------------------------------------------------------------

    def save_ingest_run(self, run: Dict) -> None:
        self._execute(
            """INSERT INTO ingest_runs
               (run_id, source_file, source_file_size, instances_found,
                eks_nodes_found, hard_blocked_found, spot_eligible_found,
                gemini_calls_used, started_at, completed_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.get("run_id", str(uuid.uuid4())),
                run.get("source_file", ""),
                run.get("source_file_size", 0),
                run.get("instances_found", 0),
                run.get("eks_nodes_found", 0),
                run.get("hard_blocked_found", 0),
                run.get("spot_eligible_found", 0),
                run.get("gemini_calls_used", 0),
                run.get("started_at", datetime.utcnow().isoformat()),
                run.get("completed_at", datetime.utcnow().isoformat()),
                run.get("status", "COMPLETED"),
            ),
        )

    # ------------------------------------------------------------------
    # Skill results
    # ------------------------------------------------------------------

    def save_skill_result(self, result: Dict) -> None:
        self._execute(
            """INSERT INTO skill_results
               (run_id, skill_name, resource_id, applied, finding,
                recommendation_generated, execution_time_ms, ran_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                result.get("run_id"),
                result.get("skill_name", ""),
                result.get("resource_id", ""),
                1 if result.get("applied") else 0,
                json.dumps(result.get("finding")) if result.get("finding") else None,
                1 if result.get("recommendation_generated") else 0,
                result.get("execution_time_ms"),
                result.get("ran_at", datetime.utcnow().isoformat()),
            ),
        )

    # ------------------------------------------------------------------
    # Skill Contributions & Admins
    # ------------------------------------------------------------------

    def create_skill_submission(self, skill_name: str, description: str, track: str, code_content: str, submitted_by: str) -> str:
        sub_id = str(uuid.uuid4())
        self._execute(
            """INSERT INTO skill_submissions (id, skill_name, description, track, code_content, submitted_by, submitted_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (sub_id, skill_name, description, track, code_content, submitted_by, datetime.utcnow().isoformat())
        )
        return sub_id

    def get_skill_submissions(self, status: Optional[str] = None) -> List[Dict]:
        if status:
            return self._fetchall("SELECT * FROM skill_submissions WHERE status = ? ORDER BY submitted_at DESC", (status,))
        return self._fetchall("SELECT * FROM skill_submissions ORDER BY submitted_at DESC")

    def review_skill_submission(self, submission_id: str, status: str, reviewed_by: str, review_notes: str) -> None:
        self._execute(
            "UPDATE skill_submissions SET status=?, reviewed_by=?, reviewed_at=?, review_notes=? WHERE id=?",
            (status, reviewed_by, datetime.utcnow().isoformat(), review_notes, submission_id)
        )

    def get_skill_admins(self) -> List[str]:
        rows = self._fetchall("SELECT email FROM skill_admins")
        return [r["email"] for r in rows]

    def add_skill_admin(self, email: str, added_by: str) -> None:
        self._execute(
            "INSERT OR IGNORE INTO skill_admins (email, added_by, added_at) VALUES (?, ?, ?)",
            (email, added_by, datetime.utcnow().isoformat())
        )

    def remove_skill_admin(self, email: str) -> None:
        self._execute("DELETE FROM skill_admins WHERE email=?", (email,))

    def seed_default_admins(self, master_admin: str, admins: List[str]) -> None:
        existing = self.get_skill_admins()
        if not existing:
            now = datetime.utcnow().isoformat()
            if master_admin and master_admin not in admins:
                admins.append(master_admin)
            for email in admins:
                self._execute(
                    "INSERT INTO skill_admins (email, added_by, added_at) VALUES (?, ?, ?)",
                    (email, 'system_init', now)
                )
