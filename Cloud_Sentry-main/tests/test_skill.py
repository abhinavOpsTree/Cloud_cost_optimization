# -*- coding: utf-8 -*-
"""
tests/test_skill.py
-------------------
Tests that the template skill and base skill classes work correctly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_pass = 0
_fail = 0

def check(name, condition, detail=""):
    global _pass, _fail
    if condition:
        print(f"  [PASS] {name}")
        _pass += 1
    else:
        print(f"  [FAIL] {name}{': ' + detail if detail else ''}")
        _fail += 1


print("\n[Test 1] Base skill classes importable")
try:
    from core.base_skill import BaseAnalysisSkill, BaseGovernanceSkill, BaseContextSkill
    check("BaseAnalysisSkill importable", True)
    check("BaseGovernanceSkill importable", True)
    check("BaseContextSkill importable", True)
except Exception as e:
    check("Base skill imports", False, str(e))


print("\n[Test 2] Template skill importable and has required methods")
try:
    from skills.analysis.template_skill import TemplateSkill
    check("TemplateSkill importable", True)

    skill = TemplateSkill()
    check("TemplateSkill instantiates", True)

    check("has can_apply", hasattr(skill, "can_apply") and callable(skill.can_apply))
    check("has analyse", hasattr(skill, "analyse") and callable(skill.analyse))
    check("has recommend", hasattr(skill, "recommend") and callable(skill.recommend))
    check("has generate_script", hasattr(skill, "generate_script") and callable(skill.generate_script))

    check("has NAME", hasattr(skill, "NAME") and skill.NAME == "template_skill")
    check("has TRACK", hasattr(skill, "TRACK"))
    check("has VERSION", hasattr(skill, "VERSION"))
except Exception as e:
    check("TemplateSkill", False, str(e))


print("\n[Test 3] Template skill methods return correct types")
try:
    skill = TemplateSkill()
    test_instance = {
        "resource_id": "i-test123",
        "resource_name": "test-instance",
        "instance_type": "t3.medium",
        "pricing_model": "OnDemand",
        "has_performance_data": True,
        "cpu_avg_pct": 5.0,
        "monthly_cost_est": 15.50,
    }

    result = skill.can_apply(test_instance)
    check("can_apply returns bool", isinstance(result, bool))

    result = skill.analyse(test_instance)
    check("analyse returns dict", isinstance(result, dict))

    result = skill.recommend(test_instance, {})
    check("recommend returns dict or None", result is None or isinstance(result, dict))

    result = skill.generate_script(test_instance, {})
    check("generate_script returns dict", isinstance(result, dict))
    check("generate_script has terraform_hcl", "terraform_hcl" in result)
    check("generate_script has aws_cli_command", "aws_cli_command" in result)
    check("generate_script has rollback_command", "rollback_command" in result)
except Exception as e:
    check("Template methods", False, str(e))


print("\n[Test 4] TemplateSkill is a proper subclass")
try:
    check("TemplateSkill extends BaseAnalysisSkill",
          issubclass(TemplateSkill, BaseAnalysisSkill))
except Exception as e:
    check("Subclass check", False, str(e))


print(f"\n{'='*50}")
print(f"Results: {_pass} passed, {_fail} failed")
print(f"{'='*50}")

if _fail == 0:
    print("\nSKILL TESTS: ALL PASSED")
    sys.exit(0)
else:
    print(f"\nSKILL TESTS: {_fail} CHECKS FAILED")
    sys.exit(1)
