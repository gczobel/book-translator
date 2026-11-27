"""Gather the merge rule's inputs from GitHub, refusing to guess when anything is incomplete.

Every partial or oddly shaped answer raises AgentPrError, which the entry point turns into a
failed job (and an escalation). The rules in `core.py` never see incomplete data.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from agentpr.core import CheckRun, OwnerReview, PullFacts
from ghapi.identities import AGENT_BOT_ID, OWNER_ID
from ghapi.repo import split_repo
from guard.collect import GITHUB_FILE_LIST_LIMIT

_SHA = re.compile(r"[0-9a-f]{40}")
_OWNER_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
_CHECK_PAGES = 40  # 4000 check runs at 100 per page; far more than a PR here has


class AgentPrError(Exception):
    """The inputs are incomplete or malformed, so the rule can't judge. Fails closed."""


class Api(Protocol):
    def get_json(self, path: str) -> Any: ...

    def get_pages(self, path: str) -> list[Any]: ...


def _obj(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentPrError(f"{what} is not an object")
    return value


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentPrError(f"{what} is not an integer")
    return value


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentPrError(f"{what} is not a string")
    return value


def _bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise AgentPrError(f"{what} is not a boolean")
    return value


def require_repo(value: Any, what: str) -> str:
    repo = _str(value, what)
    if split_repo(repo) is None:
        raise AgentPrError(f"{what} is not owner/name")
    return repo


def agent_pr_numbers(api: Api, repo: str) -> list[int]:
    """Numbers of the open PRs the Agent App wrote, lowest first, found by listing the API.

    The event that woke us up says nothing about which PR to judge: a `workflow_run`'s head_sha
    may be the base branch's tip. Only the author is checked here; `pull_facts` and the rule
    judge the rest.
    """
    numbers = []
    for raw in api.get_pages(f"/repos/{repo}/pulls?state=open"):
        pr = _obj(raw, "pull request")
        user = _obj(pr.get("user"), "pull request author")
        if _int(user.get("id"), "author id") == AGENT_BOT_ID:
            numbers.append(_int(pr.get("number"), "pull request number"))
    return sorted(numbers)


def tag_names(api: Api, repo: str) -> list[str]:
    """Every tag name starting with `v` (the release pattern), or AgentPrError if unreadable."""
    names = []
    for raw in api.get_pages(f"/repos/{repo}/git/matching-refs/tags/v"):
        ref = _str(_obj(raw, "tag ref").get("ref"), "tag ref")
        prefix = "refs/tags/"
        if not ref.startswith(prefix):
            raise AgentPrError("tag ref is not under refs/tags/")
        names.append(ref[len(prefix) :])
    return names


def pull_facts(api: Api, repo: str, number: int, owner_id: int = OWNER_ID) -> tuple[PullFacts, int]:
    """The PR's identity facts and its changed-file count. Reviews are read here too."""
    raw = _obj(api.get_json(f"/repos/{repo}/pulls/{number}"), "pull request")
    user = _obj(raw.get("user"), "pull request author")
    head = _obj(raw.get("head"), "pull request head")
    base = _obj(raw.get("base"), "pull request base")
    head_repo = _obj(head.get("repo"), "head repository")  # None when a fork was deleted
    base_repo = _obj(base.get("repo"), "base repository")
    labels = raw.get("labels")
    if not isinstance(labels, list):
        raise AgentPrError("labels are not a list")
    names = frozenset(_str(_obj(label, "label").get("name"), "label name") for label in labels)

    states = []
    for review in api.get_pages(f"/repos/{repo}/pulls/{number}/reviews"):
        r = _obj(review, "review")
        reviewer = r.get("user")
        if not isinstance(reviewer, dict):  # a deleted account is not the owner
            continue
        state = _str(r.get("state"), "review state")
        if _int(reviewer.get("id"), "reviewer id") == owner_id and state in _OWNER_REVIEW_STATES:
            states.append(OwnerReview(state, _sha(r.get("commit_id"), "review commit")))

    facts = PullFacts(
        number=_int(raw.get("number"), "pull request number"),
        state=_str(raw.get("state"), "state"),
        merged=_bool(raw.get("merged"), "merged"),
        draft=_bool(raw.get("draft"), "draft"),
        author_id=_int(user.get("id"), "author id"),
        author_type=_str(user.get("type"), "author type"),
        base_repo=require_repo(base_repo.get("full_name"), "base repository"),
        head_repo=require_repo(head_repo.get("full_name"), "head repository"),
        base_ref=_str(base.get("ref"), "base ref"),
        default_branch=_str(base_repo.get("default_branch"), "default branch"),
        head_ref=_str(head.get("ref"), "head ref"),
        head_sha=_sha(head.get("sha"), "head sha"),
        labels=names,
        owner_reviews=tuple(states),
    )
    return facts, _int(raw.get("changed_files"), "changed_files")


def _sha(value: Any, what: str) -> str:
    sha = _str(value, what)
    if not _SHA.fullmatch(sha):
        raise AgentPrError(f"{what} is not a commit hash")
    return sha


def changed_paths(api: Api, repo: str, number: int, expected: int) -> list[str]:
    """Every changed path and every rename source, or AgentPrError if the list is partial."""
    if expected >= GITHUB_FILE_LIST_LIMIT:
        raise AgentPrError(f"{expected} changed files: at or over GitHub's list limit")
    paths: list[str] = []
    count = 0
    for raw in api.get_pages(f"/repos/{repo}/pulls/{number}/files"):
        f = _obj(raw, "changed file")
        count += 1
        paths.append(_str(f.get("filename"), "filename"))
        previous = f.get("previous_filename")
        if previous is not None:
            paths.append(_str(previous, "previous filename"))
    if count != expected:
        raise AgentPrError(f"file list truncated: got {count} of {expected}")
    return paths


def check_runs(api: Api, repo: str, sha: str) -> list[CheckRun]:
    """Every check run on the commit. The endpoint wraps its list, so it is paged here."""
    runs: list[CheckRun] = []
    total: int | None = None
    for page in range(1, _CHECK_PAGES + 1):
        body = _obj(
            api.get_json(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}"),
            "check runs",
        )
        total = _int(body.get("total_count"), "total_count")
        items = body.get("check_runs")
        if not isinstance(items, list):
            raise AgentPrError("check_runs is not a list")
        for raw in items:
            c = _obj(raw, "check run")
            conclusion = c.get("conclusion")
            if conclusion is not None and not isinstance(conclusion, str):
                raise AgentPrError("check conclusion is not a string")
            runs.append(
                CheckRun(
                    id=_int(c.get("id"), "check id"),
                    name=_str(c.get("name"), "check name"),
                    status=_str(c.get("status"), "check status"),
                    conclusion=conclusion,
                    app_id=_int(_obj(c.get("app"), "check app").get("id"), "check app id"),
                )
            )
        if not items or len(runs) >= total:
            break
    if total is None or len(runs) != total:
        raise AgentPrError(f"check list truncated: got {len(runs)} of {total}")
    return runs
