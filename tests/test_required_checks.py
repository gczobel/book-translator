"""The required checks named in code must equal the ones the `main` ruleset enforces."""

import json
from pathlib import Path

from agentpr import core as agentpr_core
from arming import core as arming_core
from ghapi.identities import ACTIONS_APP_ID

RULESET = Path(__file__).resolve().parent.parent / ".github" / "rulesets" / "main.json"


def _ruleset_checks() -> list[tuple[str, int]]:
    rules = json.loads(RULESET.read_text())["rules"]
    (rule,) = [r for r in rules if r["type"] == "required_status_checks"]
    return [
        (c["context"], c["integration_id"]) for c in rule["parameters"]["required_status_checks"]
    ]


def test_every_ruleset_check_comes_from_github_actions() -> None:
    assert {app for _, app in _ruleset_checks()} == {ACTIONS_APP_ID}


def test_arming_requires_exactly_the_rulesets_checks() -> None:
    names = [name for name, _ in _ruleset_checks()]
    assert sorted(arming_core.REQUIRED_CHECKS) == sorted(names)
    assert len(set(arming_core.REQUIRED_CHECKS)) == len(arming_core.REQUIRED_CHECKS)


def test_the_agent_merge_rule_requires_exactly_the_rulesets_checks_plus_the_llm_review() -> None:
    names = sorted(name for name, _ in _ruleset_checks())
    assert sorted(agentpr_core.RULESET_CHECKS) == names
    expected = names + (["llm-review"] if agentpr_core.LLM_REVIEW_REQUIRED else [])
    assert sorted(agentpr_core.REQUIRED_CHECKS) == sorted(expected)
