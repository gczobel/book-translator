"""Whether a failed CI run on a PR is repaired, skipped or escalated (ADR 0005, "Repairs").

Pure decisions over plain data. A PR qualifies only if its author's numeric ID is Dependabot's
or the maintenance App's and its head repository is this one (invariant 2), the CI run that
failed is for the PR's current head commit, and the budget is not spent.

Attempts are counted from the branch's own commits: every commit whose subject starts with
`repair: ` is one. Identity is deliberately not checked there: a spoofed marker only spends
budget (the safe direction), while a missed real one would let the loop run forever.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from arming.core import Pull
from ghapi.identities import DEPENDABOT_ID, MAINT_BOT_ID

MAX_ATTEMPTS = 2
TRUSTED_AUTHORS = frozenset({DEPENDABOT_ID, MAINT_BOT_ID})
COMMIT_PREFIX = "repair: "


@dataclass(frozen=True)
class Decision:
    action: str  # "repair", "skip" or "escalate"
    reason: str  # why; for "escalate" an escalate reason code
    attempt: int = 0  # the attempt number when repairing


def count_attempts(subjects: Iterable[str]) -> int:
    """How many commit subjects are repair commits."""
    return sum(1 for subject in subjects if subject.startswith(COMMIT_PREFIX))


def commit_message(attempt: int) -> str:
    return f"{COMMIT_PREFIX}automated fix for failing CI (attempt {attempt} of {MAX_ATTEMPTS})"


def decide(
    pull: Pull, repo: str, run_sha: str, conclusion: str, subjects: Iterable[str]
) -> Decision:
    if conclusion != "failure":
        return Decision("skip", "the run did not fail")
    if pull.state != "open":
        return Decision("skip", "the pull request is not open")
    if pull.author_id not in TRUSTED_AUTHORS:
        return Decision("skip", "the author is not Dependabot or the maintenance App")
    if pull.head_repo != repo or pull.base_repo != repo:
        return Decision("skip", "the head repository is not this repository")
    if pull.head_sha != run_sha:
        return Decision("skip", "the failed run is for an older commit")
    used = count_attempts(subjects)
    if used >= MAX_ATTEMPTS:
        return Decision("escalate", "repair-attempts-exhausted")
    return Decision("repair", "ok", attempt=used + 1)
