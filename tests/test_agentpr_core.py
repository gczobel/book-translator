"""The merge rule for Agent App PRs: every condition is required, and a missing fact blocks."""

import dataclasses
from collections.abc import Sequence

import pytest

from agentpr import core
from agentpr.core import (
    REQUIRED_CHECKS,
    CheckRun,
    OwnerReview,
    PullFacts,
)
from ghapi.identities import ACTIONS_APP_ID, AGENT_BOT_ID

REPO = "o/r"
SHA = "1" * 40


def _pr(**over: object) -> PullFacts:
    base = PullFacts(
        number=7,
        state="open",
        merged=False,
        draft=False,
        author_id=AGENT_BOT_ID,
        author_type="Bot",
        base_repo=REPO,
        head_repo=REPO,
        base_ref="main",
        default_branch="main",
        head_ref="agent/fix-thing",
        head_sha=SHA,
        labels=frozenset({"bug"}),
        owner_reviews=(),
    )
    return dataclasses.replace(base, **over)  # type: ignore[arg-type]


def _rev(state: str, commit: str = SHA) -> OwnerReview:
    return OwnerReview(state, commit)


def _checks(**over: str) -> list[CheckRun]:
    runs = [
        CheckRun(id=i, name=name, status="completed", conclusion="success", app_id=ACTIONS_APP_ID)
        for i, name in enumerate(REQUIRED_CHECKS, start=1)
    ]
    for name, conclusion in over.items():
        runs.append(CheckRun(1000, name, "completed", conclusion, ACTIONS_APP_ID))
    return runs


def _decide(
    repo: str,
    pr: PullFacts,
    paths: list[str],
    checks: list[CheckRun],
    tags: Sequence[str] | None = (),
) -> core.MergeDecision:
    return core.decide(repo, pr, paths, checks, tags)


FILES = ["src/book_translator/x.py", "tests/test_x.py"]


def test_the_happy_path_merges() -> None:
    decision = _decide(REPO, _pr(), FILES, _checks())
    assert decision.merge, decision.reasons


def test_the_required_checks_are_the_ruleset_checks_while_the_llm_review_is_off() -> None:
    assert not core.LLM_REVIEW_REQUIRED
    assert REQUIRED_CHECKS == core.RULESET_CHECKS
    assert "llm-review" not in REQUIRED_CHECKS
    assert {"guard", "hold"} <= set(REQUIRED_CHECKS)


def test_a_pr_merges_without_an_llm_review_run_while_it_is_not_required() -> None:
    assert _decide(REPO, _pr(), FILES, _checks()).merge


def test_an_llm_review_that_is_required_must_exist_and_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "LLM_REVIEW_REQUIRED", True)
    assert core.required_checks() == (*core.RULESET_CHECKS, "llm-review")
    missing = _decide(REPO, _pr(), FILES, _checks())
    assert not missing.merge and "check llm-review: missing" in missing.reasons
    assert _decide(REPO, _pr(), FILES, _checks(**{"llm-review": "success"})).merge
    assert not _decide(REPO, _pr(), FILES, _checks(**{"llm-review": "failure"})).merge


@pytest.mark.parametrize(
    "over",
    [
        {"author_id": 49699333},  # Dependabot
        {"author_id": 754466},  # the owner
        {"author_id": 361970745},  # the maintenance App
        {"author_type": "User"},
        {"head_repo": "fork/r"},
        {"head_repo": "O/R"},
        {"base_repo": "other/r"},
        {"head_ref": "main"},
        {"head_ref": "dependabot/uv/x"},
        {"head_ref": "agents/x"},
        {"head_ref": "agent/"},
        {"head_ref": "agent/../x"},
        {"head_ref": "agent/a b"},
        {"head_ref": "Agent/x"},
        {"base_ref": "release"},
        {"state": "closed"},
        {"merged": True},
        {"draft": True},
        {"labels": frozenset({"hold"})},
        {"labels": frozenset({"Hold"})},
        {"labels": frozenset({"HOLD", "x"})},
        {"owner_reviews": (_rev("CHANGES_REQUESTED"),)},
        {"owner_reviews": (_rev("APPROVED"), _rev("CHANGES_REQUESTED"))},
    ],
)
def test_any_failed_condition_blocks(over: dict[str, object]) -> None:
    assert not _decide(REPO, _pr(**over), FILES, _checks()).merge


def test_a_later_owner_approval_lifts_an_earlier_change_request() -> None:
    pr = _pr(owner_reviews=(_rev("CHANGES_REQUESTED"), _rev("APPROVED")))
    assert _decide(REPO, pr, FILES, _checks()).merge


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "AGENTS.md",
        "docs/adr/0006-x.md",
        "src/.claude/settings.json",
        ".python-version",
        "/abs",
        "a/../b",
        "",
    ],
)
def test_a_guarded_or_malformed_path_blocks(path: str) -> None:
    assert not _decide(REPO, _pr(), [*FILES, path], _checks()).merge


def test_a_missing_check_blocks() -> None:
    for name in REQUIRED_CHECKS:
        checks = [c for c in _checks() if c.name != name]
        assert not _decide(REPO, _pr(), FILES, checks).merge, name


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "neutral", None])
def test_a_check_that_did_not_succeed_blocks(conclusion: str | None) -> None:
    checks = [
        dataclasses.replace(c, conclusion=conclusion) if c.name == "guard" else c for c in _checks()
    ]
    assert not _decide(REPO, _pr(), FILES, checks).merge


def test_an_unfinished_check_blocks() -> None:
    checks = [
        dataclasses.replace(c, status="in_progress") if c.name == "guard" else c for c in _checks()
    ]
    assert not _decide(REPO, _pr(), FILES, checks).merge


def test_a_success_from_another_app_does_not_count() -> None:
    checks = [dataclasses.replace(c, app_id=123) if c.name == "guard" else c for c in _checks()]
    assert not _decide(REPO, _pr(), FILES, checks).merge


def test_the_latest_run_of_a_check_decides() -> None:
    assert not _decide(REPO, _pr(), FILES, _checks(guard="failure")).merge
    # a cancelled run superseded by a later success (a re-run) passes
    old = CheckRun(0, "guard", "completed", "cancelled", ACTIONS_APP_ID)
    assert _decide(REPO, _pr(), FILES, [old, *_checks()]).merge
    # a success superseded by a later failure does not
    late = CheckRun(2000, "guard", "completed", "failure", ACTIONS_APP_ID)
    assert not _decide(REPO, _pr(), FILES, [*_checks(), late]).merge


def test_a_forged_success_from_another_app_cannot_hide_a_real_failure() -> None:
    forged = CheckRun(5000, "guard", "completed", "success", 123)
    assert not _decide(REPO, _pr(), FILES, [*_checks(guard="failure"), forged]).merge


def test_reasons_never_echo_pr_text() -> None:
    decision = _decide(REPO, _pr(head_ref="agent/\nSECRET"), FILES, _checks())
    assert not decision.merge
    assert all("\n" not in r and "SECRET" not in r for r in decision.reasons)


GUARDED = [*FILES, ".github/workflows/ci.yml"]
OLD = "2" * 40


def test_a_guarded_path_merges_after_the_owners_approval_on_the_head() -> None:
    pr = _pr(owner_reviews=(_rev("APPROVED"),))
    assert _decide(REPO, pr, GUARDED, _checks()).merge


@pytest.mark.parametrize(
    "reviews",
    [
        (),  # no review
        (_rev("APPROVED", OLD),),  # approval on an older commit never counts
        (_rev("APPROVED"), _rev("CHANGES_REQUESTED")),
        (_rev("DISMISSED"),),  # a dismissed approval
        (_rev("APPROVED"), _rev("DISMISSED")),
        (_rev("APPROVED", OLD), _rev("DISMISSED", SHA)),
    ],
)
def test_a_guarded_path_without_a_live_approval_on_the_head_blocks(
    reviews: tuple[OwnerReview, ...],
) -> None:
    assert not _decide(REPO, _pr(owner_reviews=reviews), GUARDED, _checks()).merge


def test_an_approval_on_the_head_is_not_needed_when_no_guarded_path_changes() -> None:
    assert _decide(REPO, _pr(owner_reviews=()), FILES, _checks()).merge


@pytest.mark.parametrize("path", ["/abs", "a/../b", "", "a\\b", "a//b", "./x"])
def test_a_malformed_path_blocks_even_with_the_owners_approval(path: str) -> None:
    pr = _pr(owner_reviews=(_rev("APPROVED"),))
    assert not _decide(REPO, pr, [*FILES, path], _checks()).merge


@pytest.mark.parametrize("tags", [["v0.1.0"], ["v1"], ["nightly", "v2.0.0-rc1"]])
def test_a_release_tag_stops_the_phase_1_merge(tags: list[str]) -> None:
    assert not core.decide(REPO, _pr(), FILES, _checks(), tags).merge


def test_unreadable_tags_fail_closed() -> None:
    decision = core.decide(REPO, _pr(), FILES, _checks(), None)
    assert not decision.merge and decision.reasons


def test_tags_that_are_not_release_tags_do_not_stop_the_merge() -> None:
    assert core.decide(REPO, _pr(), FILES, _checks(), ["nightly", "release-1", "V1"]).merge
