"""The repair decision: which PRs are repaired, and when the budget is spent. Seam: `decide`."""

from typing import Any

from arming.core import Pull
from ghapi.identities import AGENT_BOT_ID, DEPENDABOT_ID, MAINT_BOT_ID
from repair.core import MAX_ATTEMPTS, count_attempts, decide

REPO = "o/r"
SHA = "a" * 40


def pull(**over: Any) -> Pull:
    fields: dict[str, Any] = {
        "number": 7,
        "node_id": "PR_7",
        "state": "open",
        "author_id": DEPENDABOT_ID,
        "head_repo": REPO,
        "base_repo": REPO,
        "head_ref": "dependabot/uv/x-1",
        "base_ref": "main",
        "head_sha": SHA,
        "labels": frozenset(),
        "armed": False,
    }
    fields.update(over)
    return Pull(**fields)


def test_a_failed_ci_run_on_a_dependabot_pr_is_repaired_on_the_first_attempt() -> None:
    d = decide(pull(), REPO, SHA, "failure", [])
    assert (d.action, d.attempt) == ("repair", 1)


def test_the_maintenance_app_pr_is_repaired_too() -> None:
    d = decide(pull(author_id=MAINT_BOT_ID, head_ref="release-please--x"), REPO, SHA, "failure", [])
    assert d.action == "repair"


def test_other_authors_are_never_repaired() -> None:
    for author in (AGENT_BOT_ID, 754466, 1):
        assert decide(pull(author_id=author), REPO, SHA, "failure", []).action == "skip"


def test_a_head_repository_other_than_this_one_is_skipped() -> None:
    assert decide(pull(head_repo="evil/r"), REPO, SHA, "failure", []).action == "skip"
    assert decide(pull(head_repo=None), REPO, SHA, "failure", []).action == "skip"


def test_a_run_that_did_not_fail_is_skipped() -> None:
    for conclusion in ("success", "cancelled", "skipped", "", "neutral"):
        assert decide(pull(), REPO, SHA, conclusion, []).action == "skip"


def test_a_run_for_an_older_commit_is_skipped() -> None:
    assert decide(pull(head_sha="b" * 40), REPO, SHA, "failure", []).action == "skip"


def test_a_closed_pr_is_skipped() -> None:
    assert decide(pull(state="closed"), REPO, SHA, "failure", []).action == "skip"


def test_only_commits_marked_as_repairs_are_counted() -> None:
    subjects = ["Bump x from 1 to 2", "repair: automated fix (attempt 1 of 2)", "fix: other"]
    assert count_attempts(subjects) == 1


def test_a_look_alike_subject_is_not_a_repair() -> None:
    assert count_attempts(["Repair: x", " repair: x", "repairs: x", "chore: repair: x"]) == 0


def test_the_second_attempt_is_numbered() -> None:
    d = decide(pull(), REPO, SHA, "failure", ["repair: automated fix (attempt 1 of 2)"])
    assert (d.action, d.attempt) == ("repair", 2)


def test_a_spent_budget_escalates_instead_of_repairing() -> None:
    d = decide(pull(), REPO, SHA, "failure", ["repair: a"] * MAX_ATTEMPTS)
    assert (d.action, d.reason) == ("escalate", "repair-attempts-exhausted")


def test_the_budget_is_two_attempts() -> None:
    assert MAX_ATTEMPTS == 2
