"""Which PRs the arming workflow may arm. Seam: `arming.core.evaluate` (pure)."""

from dataclasses import replace
from typing import Any

import pytest

from arming.core import ArmDecision, LabelEvent, Pull, evaluate
from ghapi.identities import DEPENDABOT_ID, MAINT_BOT_ID, OWNER_ID

REPO = "o/r"
SHA = "a" * 40


def pull(**changes: Any) -> Pull:
    base = Pull(
        number=7,
        node_id="PR_x",
        state="open",
        author_id=DEPENDABOT_ID,
        head_repo=REPO,
        base_repo=REPO,
        head_ref="dependabot/uv/requests-2.40",
        base_ref="main",
        head_sha=SHA,
        labels=frozenset({"dependencies"}),
        armed=False,
    )
    return replace(base, **changes)


def decide(p: Pull, events: list[LabelEvent] | None = None) -> ArmDecision:
    return evaluate(p, REPO, "main", events or [])


def test_a_dependabot_pr_from_this_repo_qualifies() -> None:
    d = decide(pull())
    assert d.arm and not d.security and not d.urgent


def test_a_release_please_pr_by_the_maintenance_app_qualifies() -> None:
    d = decide(pull(author_id=MAINT_BOT_ID, head_ref="release-please--branches--main"))
    assert d.arm


@pytest.mark.parametrize(
    "changes",
    [
        {"author_id": 12345},  # an Agent App or a stranger
        {"author_id": MAINT_BOT_ID},  # right bot, dependabot branch
        {"head_ref": "release-please--branches--main"},  # dependabot author, wrong branch
        {"head_ref": "agent/dependabot/x"},  # prefix must be at the start
        {"head_ref": "Dependabot/x"},
        {"head_repo": "fork/r"},
        {"head_repo": None},
        {"base_repo": "other/r"},
        {"base_ref": "develop"},
        {"state": "closed"},
        {"labels": frozenset({"hold"})},
        {"labels": frozenset({"hold", "dependencies"})},
    ],
)
def test_everything_else_is_not_armed(changes: dict[str, Any]) -> None:
    assert not decide(pull(**changes)).arm


def labeled(label: str, actor: int | None, action: str = "labeled") -> LabelEvent:
    return LabelEvent(label=label, action=action, actor_id=actor)


def test_urgent_counts_only_when_the_owner_applied_it() -> None:
    p = pull(labels=frozenset({"urgent", "security"}))
    events = [labeled("security", DEPENDABOT_ID), labeled("urgent", OWNER_ID)]
    d = decide(p, events)
    assert d.security and d.urgent


@pytest.mark.parametrize("actor", [DEPENDABOT_ID, MAINT_BOT_ID, 999, None])
def test_urgent_by_anyone_else_is_ignored(actor: int | None) -> None:
    p = pull(labels=frozenset({"urgent", "security"}))
    d = decide(p, [labeled("security", DEPENDABOT_ID), labeled("urgent", actor)])
    assert d.arm and not d.urgent


def test_urgent_without_any_event_is_ignored() -> None:
    assert not decide(pull(labels=frozenset({"urgent"}))).urgent


def test_the_latest_event_decides_who_applied_urgent() -> None:
    p = pull(labels=frozenset({"urgent"}))
    owner_then_stranger = [labeled("urgent", OWNER_ID), labeled("urgent", 999)]
    assert not decide(p, owner_then_stranger).urgent
    removed = [labeled("urgent", OWNER_ID), labeled("urgent", OWNER_ID, "unlabeled")]
    assert not decide(p, removed).urgent


def test_urgent_event_without_the_label_present_is_ignored() -> None:
    assert not decide(pull(), [labeled("urgent", OWNER_ID)]).urgent


def test_label_names_are_case_insensitive() -> None:
    # labels reach the core already lower-cased by the collector; events are matched the same way
    p = pull(labels=frozenset({"urgent"}))
    assert decide(p, [labeled("Urgent", OWNER_ID)]).urgent


def test_security_label_counts_only_when_dependabot_applied_it() -> None:
    p = pull(labels=frozenset({"security"}))
    assert decide(p, [labeled("security", DEPENDABOT_ID)]).security
    assert not decide(p, [labeled("security", 999)]).security
    assert not decide(p, []).security
    # the owner is not Dependabot: the stricter 7-day rule applies
    assert not decide(p, [labeled("security", OWNER_ID)]).security


def test_whether_a_pr_is_already_armed_does_not_change_whether_it_qualifies() -> None:
    assert decide(pull(armed=True)).arm
    assert not decide(pull(armed=True, labels=frozenset({"hold"}))).arm
