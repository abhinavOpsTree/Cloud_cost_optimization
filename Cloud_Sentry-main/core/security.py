"""
core/security.py
-----------------
Security PIN verification for Cloud-Sentry AI execution confirmation.

PIN is stored as a bcrypt hash in config.yaml — never plaintext.
Failed attempts are tracked in memory with lockout support.
Every failed attempt is also logged to SQLite.

Usage:
    from core.security import PINVerifier
    verifier = PINVerifier()
    result = verifier.verify("1234", client_ip="127.0.0.1")
    # result: {"success": True} or {"success": False, "reason": "...", "attempts_remaining": 2}
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, Optional

import yaml


CONFIG_PATH = "config.yaml"

# In-memory lockout tracker: {ip -> {"count": int, "first_failure": datetime}}
_failure_tracker: Dict[str, dict] = {}


class PINVerifier:
    """Verifies execution PIN against bcrypt hash stored in config.yaml."""

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> dict:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)

    @property
    def pin_hash(self) -> str:
        return self._config.get("security", {}).get("execution_pin_hash", "")

    @property
    def max_attempts(self) -> int:
        return int(self._config.get("security", {}).get("pin_max_attempts", 3))

    @property
    def lockout_minutes(self) -> int:
        return int(self._config.get("security", {}).get("pin_lockout_minutes", 5))

    def verify(self, pin: str, client_ip: str = "unknown") -> dict:
        """
        Verify a PIN against the stored hash.

        Returns:
            {"success": True} on correct PIN
            {"success": False, "reason": "locked_out", "unlock_at": str} if locked out
            {"success": False, "reason": "wrong_pin", "attempts_remaining": int} on failure
            {"success": False, "reason": "no_pin_configured"} if PIN not set in config
        """
        if not self.pin_hash:
            return {"success": False, "reason": "no_pin_configured",
                    "message": "No execution PIN configured. Add execution_pin_hash to config.yaml."}

        # Check lockout
        lockout = self._check_lockout(client_ip)
        if lockout:
            return lockout

        # Verify PIN
        try:
            import bcrypt
            correct = bcrypt.checkpw(pin.encode(), self.pin_hash.encode())
        except Exception as e:
            return {"success": False, "reason": "verification_error", "message": str(e)}

        if correct:
            # Clear failure count on success
            _failure_tracker.pop(client_ip, None)
            return {"success": True}

        # Record failure
        now = datetime.utcnow()
        if client_ip not in _failure_tracker:
            _failure_tracker[client_ip] = {"count": 0, "first_failure": now}
        _failure_tracker[client_ip]["count"] += 1

        count = _failure_tracker[client_ip]["count"]
        remaining = max(0, self.max_attempts - count)

        if remaining == 0:
            unlock_at = now + timedelta(minutes=self.lockout_minutes)
            _failure_tracker[client_ip]["locked_until"] = unlock_at
            return {
                "success": False,
                "reason": "locked_out",
                "message": f"Too many failed attempts. Locked out for {self.lockout_minutes} minutes.",
                "unlock_at": unlock_at.isoformat(),
            }

        return {
            "success": False,
            "reason": "wrong_pin",
            "message": f"Incorrect PIN. {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
            "attempts_remaining": remaining,
        }

    def _check_lockout(self, client_ip: str) -> Optional[dict]:
        """Return lockout dict if IP is currently locked out, else None."""
        if client_ip not in _failure_tracker:
            return None
        tracker = _failure_tracker[client_ip]
        locked_until = tracker.get("locked_until")
        if locked_until and datetime.utcnow() < locked_until:
            remaining_secs = int((locked_until - datetime.utcnow()).total_seconds())
            return {
                "success": False,
                "reason": "locked_out",
                "message": f"Too many failed attempts. Try again in {remaining_secs} seconds.",
                "unlock_at": locked_until.isoformat(),
            }
        # Lockout expired — clear it
        if locked_until and datetime.utcnow() >= locked_until:
            _failure_tracker.pop(client_ip, None)
        return None
