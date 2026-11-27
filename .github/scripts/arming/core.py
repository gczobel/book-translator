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

from ghapi.identities import DEPENDABOT_ID, MAINT_BOT_ID, OWNER_ID

# author ID -> head-branch prefix that author may use
ARMABLE_AUTHORS: dict[int, str] = {
    DEPENDABOT_ID: "dependabot/",
    MAINT_BOT_ID: "release-please--",
}

HOLD = "hold"
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
class LabelEvent:
    label: str
    action: str  # "labeled" or "unlabeled"
    actor_id: int | None


@dataclass(frozen=True)
class Decision:
    arm: bool
    reason: str
    security: bool = False
    urgent: bool = False


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


def evaluate(pull: Pull, repo: str, default_branch: str, events: Iterable[LabelEvent]) -> Decision:
    """Whether `pull` may be armed, and the policy inputs for the age gate.

    `security` is honoured only if Dependabot itself applied the label and `urgent` only if the
    owner did; otherwise they are false, which is the stricter reading (7 days, no skip).
    """
    prefix = ARMABLE_AUTHORS.get(pull.author_id)
    if prefix is None:
        return Decision(False, "author is not Dependabot or the maintenance App")
    if not pull.head_ref.startswith(prefix):
        return Decision(False, "head branch does not match the author")
    if pull.head_repo != repo or pull.base_repo != repo:
        return Decision(False, "head or base repository is not this repository")
    if pull.base_ref != default_branch:
        return Decision(False, "base branch is not the default branch")
    if pull.state != "open":
        return Decision(False, "not open")
    if pull.armed:
        return Decision(False, "already armed")
    if HOLD in pull.labels:
        return Decision(False, "on hold")
    events = list(events)
    security = SECURITY in pull.labels and _applied_by(events, SECURITY, {DEPENDABOT_ID})
    urgent = URGENT in pull.labels and _applied_by(events, URGENT, {OWNER_ID})
    return Decision(True, "qualifies", security=security, urgent=urgent)
