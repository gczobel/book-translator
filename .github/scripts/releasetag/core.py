"""Does a new `v*` tag point at a release-please merge commit on main? (ADR 0005, "Releases")

Pure decisions over plain data, so the rules are unit-tested without GitHub. The tag name is
data: it is checked against a strict pattern before anything else. The commit must be reachable
from main, be a squash merge (one parent), and be the merge commit of exactly one pull request
that the maintenance App (numeric ID, never the login) opened from a release-please branch of
this repository into main, whose title is the one release-please was configured to write for
this very version.

Release-please names its branch `release-please--branches--<target-branch>` (release-please's
`RELEASE_PLEASE_BRANCH_PREFIX`; a component adds `--components--<name>`, which this single
package project never uses). The title pattern is pinned in release-please-config.json.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ghapi.identities import MAINT_BOT_ID

TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RELEASE_BRANCH_PREFIX = "release-please--branches--"
# Must equal "pull-request-title-pattern" in release-please-config.json (a test checks it).
TITLE_PATTERN = "chore: release ${version}"


@dataclass(frozen=True)
class MergedPull:
    number: int
    author_id: int | None
    head_repo: str | None  # None when the fork is gone
    base_repo: str | None
    head_ref: str
    base_ref: str
    merge_commit_sha: str | None
    merged: bool
    title: str


@dataclass(frozen=True)
class TagFacts:
    tag: str
    commit_sha: str  # the commit the tag points at, annotated tags peeled
    on_main: bool  # reachable from main
    parent_count: int
    pulls: tuple[MergedPull, ...]  # every pull request GitHub associates with the commit


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str


def expected_title(tag: str) -> str:
    return TITLE_PATTERN.replace("${version}", tag.removeprefix("v"))


def verify(facts: TagFacts, repo: str, default_branch: str) -> Verdict:
    """Accept only a tag on the merge commit of the maintenance App's release-please PR."""
    if TAG.fullmatch(facts.tag) is None:
        return Verdict(False, "tag name is not vMAJOR.MINOR.PATCH")
    if not facts.on_main:
        return Verdict(False, "tagged commit is not reachable from the default branch")
    if facts.parent_count != 1:
        return Verdict(False, "tagged commit is not a squash merge (needs exactly one parent)")
    if len(facts.pulls) != 1:
        return Verdict(False, f"tagged commit has {len(facts.pulls)} pull requests, expected 1")
    pull = facts.pulls[0]
    if not pull.merged or pull.merge_commit_sha != facts.commit_sha:
        return Verdict(False, "tagged commit is not the pull request's merge commit")
    if pull.author_id != MAINT_BOT_ID:
        return Verdict(False, "pull request was not opened by the maintenance App")
    if not pull.head_ref.startswith(RELEASE_BRANCH_PREFIX):
        return Verdict(False, "pull request head branch is not release-please's")
    if pull.head_repo != repo or pull.base_repo != repo:
        return Verdict(False, "pull request head or base repository is not this repository")
    if pull.base_ref != default_branch:
        return Verdict(False, "pull request base is not the default branch")
    if pull.title != expected_title(facts.tag):
        return Verdict(False, "pull request title does not release this version")
    return Verdict(True, f"{facts.tag} is release-please's merge #{pull.number} on main")
