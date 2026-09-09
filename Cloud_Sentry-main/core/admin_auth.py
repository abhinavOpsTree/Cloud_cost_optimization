"""
core/admin_auth.py
-------------------
Access control for the Skill Contribution admin actions.

# SECURITY TODO: this trusts the X-User-Email header as-is. A browser can set
# this header to any value. This is only genuinely secure once the header is
# populated by verified identity from UnitEconPro's Microsoft/Azure login flow
# (pending confirmation on the exact mechanism — see conversation with Harshit).
# Until then, this is a real improvement over no access control, but not
# cryptographically tamper-proof.
"""
from core.state_store import StateStore
import yaml
import os

def _load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)

def get_master_admin() -> str:
    return _load_config().get("skill_contribution", {}).get("master_admin", "")

def is_admin(email: str, store: StateStore) -> bool:
    if not email:
        return False
    admins = store.get_skill_admins()
    return email in admins or email == get_master_admin()

def is_master_admin(email: str) -> bool:
    return bool(email) and email == get_master_admin()
