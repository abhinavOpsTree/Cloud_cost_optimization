# Contributing a Skill to Cloud-Sentry AI

## Overview

Cloud-Sentry AI uses a modular skill architecture. Each analysis skill is a
single Python file that implements 4 methods. You can add a new skill in
15-30 minutes by copying the template.

## Quick Start

```bash
# 1. Copy the template
cp skills/analysis/template_skill.py skills/analysis/my_new_skill.py

# 2. Edit the file — implement 4 methods:
#    can_apply()       → which instances does this skill target?
#    analyse()         → what does it find?
#    recommend()       → what action does it suggest?
#    generate_script() → what scripts does it produce?

# 3. Register in core/skill_registry.py
#    Add your skill to the ANALYSIS_SKILLS list

# 4. Test
python -c "from skills.analysis.my_new_skill import MyNewSkill; print('OK')"

# 5. Run the full suite
python tests/test_skill.py
```

## The 4 Methods

### 1. `can_apply(instance) -> bool`

Decide if your skill is relevant for this instance. Return `True` to run
the analysis, `False` to skip.

**Available instance data:**
| Field | Type | Description |
|-------|------|-------------|
| `resource_id` | str | AWS instance ID (e.g. i-0abc123) |
| `resource_name` | str | Instance name tag |
| `instance_type` | str | e.g. t3.medium, c5.2xlarge |
| `pricing_model` | str | "OnDemand" or "Spot" |
| `cpu_avg_pct` | float or None | Average CPU (None = no data) |
| `cpu_max_pct` | float or None | Peak CPU |
| `net_in_mbps` | float or None | Network in |
| `has_performance_data` | bool | True if CPU data exists |
| `inferred_env` | str | production/staging/test/dev/unknown |
| `inferred_workload` | str | EKS_NODE/NETWORK_GATEWAY/UNKNOWN |
| `safety_tier` | str | HARD_BLOCK/FLAG/APPROVE |
| `is_spot_eligible` | bool | True if can convert to Spot |
| `monthly_cost_est` | float | Estimated monthly cost |
| `cluster_name` | str or None | EKS cluster name |

### 2. `analyse(instance) -> dict`

Run your analysis logic. Return a findings dict, or `{}` if no action needed.

### 3. `recommend(instance, finding) -> dict | None`

Convert your finding into a recommendation. Return `None` if no action.

**Required recommendation fields:**
```python
{
    "track": "rightsizing",              # or: spot, schedule, eks, tagging
    "action": "Downsize to t3.small",    # human-readable
    "current_monthly_cost": 15.50,
    "estimated_monthly_saving": 8.00,
    "saving_pct": 51.6,
    "confidence": 0.85,
    "rationale": "CPU avg 2.5% — severely over-provisioned",
    "has_performance_data": True,
    "skill_name": "my_new_skill",
}
```

### 4. `generate_script(instance, recommendation) -> dict`

Produce copy-paste-ready scripts. Always include a rollback command.

```python
{
    "terraform_hcl": "resource ...",
    "aws_cli_command": "aws ec2 modify-instance-attribute ...",
    "rollback_command": "aws ec2 modify-instance-attribute ...",
    "eventbridge_rule": "",  # only for schedule track
}
```

## Rules

1. **Never touch production instances** — `safety_tier == "HARD_BLOCK"` must
   be skipped in `can_apply()`.
2. **Use real instance IDs** — scripts must contain actual resource_id values.
3. **Always generate rollback** — no execution without a way to undo.
4. **Don't call Gemini directly** — use `core.llm_client.call_gemini()` if
   you need AI reasoning.
5. **Log your results** — the skill registry handles this automatically.

## Existing Skills (for reference)

| Skill | Track | File |
|-------|-------|------|
| Rightsizing | rightsizing | `skills/analysis/rightsizing.py` |
| Spot Conversion | spot | `skills/analysis/spot_conversion.py` |
| Schedule Policy | schedule | `skills/analysis/schedule_policy.py` |
| EKS Diagnosis | eks | `skills/analysis/eks_diagnosis.py` |

## Support

Open an issue or ask in the #cloud-sentry Slack channel.
