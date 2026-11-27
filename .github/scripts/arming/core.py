"""Which pull requests the arming workflow may arm (ADR 0005, invariants 2 and 3).

Pure decisions over plain data, so the rules are unit-tested without GitHub. Identity is the
numeric account ID, never the login. Only two kinds of PR qualify, and the author and the head
branch prefix must match as a pair:

- Dependabot (ID 49699333) on a `dependabot/` branch.
- release-please, which runs as the maintenance App (ID 361970745), on a `release-please--` branch.

Anything else, the Agent App's PRs included, is never armed. Label names are compared in lower
case because GitHub treats them case-insensitively.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ghapi.identities import ACTIONS_APP_ID, DEPENDABOT_ID, MAINT_BOT_ID, OWNER_ID
from ghapi.labels import is_on_hold

# author ID -> head-branch prefix that author may use
ARMABLE_AUTHORS: dict[int, str] = {
    DEPENDABOT_ID: "dependabot/",
    MAINT_BOT_ID: "release-please--",
}

# The checks the `main` ruleset requires (a test keeps this equal to .github/rulesets/main.json).
# Arming's direct-merge fallback verifies every one itself, because it bypasses the merge queue's
# own waiting.
REQUIRED_CHECKS = (
    "lint",
    "typecheck",
    "test",
    "e2e",
    "epubcheck",
    "workflow-security",
    "guard",
    "hold",
)

URGENT = "urgent"
SECURITY = "security"


@dataclass(frozen=True)
class Pull:
    number: int
    node_id: str
    state: str
    author_id: int
    head_repo: str | None  # None when the fork is gone
    base_repo: str
    head_ref: str
    base_ref: str
    head_sha: str
    labels: frozenset[str]  # lower-case names
    armed: bool  # auto-merge already enabled


@dataclass(frozen=True)
class CheckRun:
    id: int
    name: str
    status: str
    conclusion: str | None
    app_id: int


@dataclass(frozen=True)
class LabelEvent:
    label: str
    action: str  # "labeled" or "unlabeled"
    actor_id: int | None


@dataclass(frozen=True)
class ArmDecision:
    arm: bool
    reason: str
    security: bool = False
    urgent: bool = False


def unverified_checks(runs: Iterable[CheckRun]) -> list[str]:
    """Required checks that are not verified successful. Empty means every one succeeded.

    Only GitHub Actions' own runs count, and the newest run of a name decides (a re-run
    supersedes). A missing, unfinished, skipped, neutral or failed check is unverified.
    """
    runs = list(runs)
    unverified = []
    for name in REQUIRED_CHECKS:
        ours = [r for r in runs if r.name == name and r.app_id == ACTIONS_APP_ID]
        latest = max(ours, key=lambda r: r.id) if ours else None
        if latest is None or latest.status != "completed" or latest.conclusion != "success":
            unverified.append(name)
    return unverified


def _applied_by(events: Iterable[LabelEvent], label: str, allowed: set[int]) -> bool:
    """True if the most recent event for `label` added it and an allowed account did so."""
    latest: LabelEvent | None = None
    for event in events:
        if event.label.lower() == label:
            latest = event
    return (
        latest is not None
        and latest.action == "labeled"
        and latest.actor_id is not None
        and latest.actor_id in allowed
    )


def evaluate(
    pull: Pull, repo: str, default_branch: str, events: Iterable[LabelEvent]
) -> ArmDecision:
    """Whether `pull` may be armed, and the policy inputs for the age gate.

    `security` is honoured only if Dependabot itself applied the label and `urgent` only if the
    owner did; otherwise they are false, which is the stricter reading (7 days, no skip).
    """
    prefix = ARMABLE_AUTHORS.get(pull.author_id)
    if prefix is None:
        return ArmDecision(False, "author is not Dependabot or the maintenance App")
    if not pull.head_ref.startswith(prefix):
        return ArmDecision(False, "head branch does not match the author")
    if pull.head_repo != repo or pull.base_repo != repo:
        return ArmDecision(False, "head or base repository is not this repository")
    if pull.base_ref != default_branch:
        return ArmDecision(False, "base branch is not the default branch")
    if pull.state != "open":
        return ArmDecision(False, "not open")
    if pull.armed:
        return ArmDecision(False, "already armed")
    if is_on_hold(pull.labels):
        return ArmDecision(False, "on hold")
    events = list(events)
    security = SECURITY in pull.labels and _applied_by(events, SECURITY, {DEPENDABOT_ID})
    urgent = URGENT in pull.labels and _applied_by(events, URGENT, {OWNER_ID})
    return ArmDecision(True, "qualifies", security=security, urgent=urgent)
