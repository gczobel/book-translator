"""The merge rule for Agent App pull requests, phase 1 (ADR 0005, "Code PRs from agents").

Pure functions over plain data. Until the first release an agent's PR merges by itself when
every condition below holds (the LLM review is not one of them yet: see LLM_REVIEW_REQUIRED).
Each one is required, and a fact that is missing or odd blocks the merge.
The rule never reads PR text (title, body, commit messages): only IDs, names of branches and
files, labels and check results.

Pause is not decided here: the workflow only runs this behind the pause gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ghapi.identities import AGENT_BOT_ID
from ghapi.labels import is_on_hold
from guard.rules import is_guarded_path

ACTIONS_APP_ID = 15368  # GitHub Actions: the only source the required checks are trusted from
BRANCH_PREFIX = "agent/"
_BRANCH = re.compile(r"agent/[A-Za-z0-9][A-Za-z0-9._/-]*")
_BAD_PARTS = {"", ".", ".."}

# The checks the `main` ruleset requires (a test keeps this equal to .github/rulesets/main.json).
RULESET_CHECKS = (
    "lint",
    "typecheck",
    "test",
    "e2e",
    "epubcheck",
    "workflow-security",
    "guard",
    "hold",
)

# TEMPORARY (decided in #25, ADR 0005): the LLM reviewer is not built, so the agent merge rule
# does not require `llm-review` yet. The `agent-pr-review` placeholder job stays red on agent PRs
# on purpose: adding `llm-review` as a required check before a real reviewer exists must block,
# not silently pass. Flip this to True once the reviewer exists (#25 stays open until then).
LLM_REVIEW_REQUIRED = False


def required_checks() -> tuple[str, ...]:
    """The checks an agent PR needs, all aggregator jobs from GitHub Actions."""
    return (*RULESET_CHECKS, "llm-review") if LLM_REVIEW_REQUIRED else RULESET_CHECKS


REQUIRED_CHECKS = required_checks()


@dataclass(frozen=True)
class PullFacts:
    number: int
    state: str
    merged: bool
    draft: bool
    author_id: int
    author_type: str
    base_repo: str
    head_repo: str
    base_ref: str
    default_branch: str
    head_ref: str
    head_sha: str
    labels: frozenset[str]
    # The owner's APPROVED / CHANGES_REQUESTED / DISMISSED reviews, oldest first.
    owner_review_states: tuple[str, ...]


@dataclass(frozen=True)
class CheckRun:
    id: int
    name: str
    status: str
    conclusion: str | None
    app_id: int


@dataclass(frozen=True)
class MergeDecision:
    merge: bool
    reasons: tuple[str, ...] = ()  # fixed wording only, never PR-controlled text


def is_agent_pr(repo: str, pr: PullFacts) -> bool:
    """Identity only: the Agent App wrote it, from a branch of this very repository."""
    return (
        pr.author_id == AGENT_BOT_ID
        and pr.author_type == "Bot"
        and pr.base_repo == repo
        and pr.head_repo == repo
    )


def _branch_ok(ref: str) -> bool:
    return _BRANCH.fullmatch(ref) is not None and not any(
        part in _BAD_PARTS for part in ref.split("/")
    )


def _check_reasons(runs: Sequence[CheckRun]) -> list[str]:
    reasons = []
    for name in required_checks():
        # Only Actions' own runs count, and the newest of them decides (a re-run supersedes).
        ours = [r for r in runs if r.name == name and r.app_id == ACTIONS_APP_ID]
        if not ours:
            reasons.append(f"check {name}: missing")
            continue
        latest = max(ours, key=lambda r: r.id)
        if latest.status != "completed" or latest.conclusion != "success":
            reasons.append(f"check {name}: not successful")
    return reasons


def decide(
    repo: str,
    pr: PullFacts,
    paths: Sequence[str],
    checks: Sequence[CheckRun],
) -> MergeDecision:
    """May this PR merge now? `paths` holds every changed path, and every rename source."""
    reasons: list[str] = []
    if not is_agent_pr(repo, pr):
        reasons.append("not written by the Agent App from this repository")
    if not _branch_ok(pr.head_ref):
        reasons.append(f"head branch is not under {BRANCH_PREFIX}")
    if pr.state != "open" or pr.merged or pr.draft:
        reasons.append("not an open, ready pull request")
    if pr.base_ref != pr.default_branch:
        reasons.append("does not target the default branch")
    if is_on_hold(pr.labels):
        reasons.append("on hold")
    if pr.owner_review_states and pr.owner_review_states[-1] == "CHANGES_REQUESTED":
        reasons.append("the owner requested changes")
    if any(is_guarded_path(p) for p in paths):
        reasons.append("touches a guarded path or a malformed path: needs the owner")
    reasons += _check_reasons(checks)
    return MergeDecision(merge=not reasons, reasons=tuple(reasons))
