"""Gather the guard's inputs from GitHub, refusing to guess when anything is incomplete.

Every way the data can be partial (a truncated file list, a truncated tree, a missing
head repository, an unexpected shape) raises GuardError, which the entry point turns into
a failing check. The rules in `rules.py` never see incomplete data.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from guard import rules

GITHUB_FILE_LIST_LIMIT = 3000  # the PR files API never returns more than this

_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class GuardError(Exception):
    """The inputs are incomplete or malformed, so the guard can't judge. Fails closed."""


class Api(Protocol):
    def get_json(self, path: str) -> Any: ...

    def get_pages(self, path: str) -> list[Any]:
        """Every item of a paginated list endpoint; raises GuardError if it can't get all."""
        ...

    def get_text(self, path: str) -> str | None:
        """A file's raw text, or None if it doesn't exist."""
        ...


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardError(f"{what} is not an integer")
    return value


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise GuardError(f"{what} is not a string")
    return value


def _sha(value: Any, what: str) -> str:
    sha = _str(value, what)
    if not _SHA.fullmatch(sha):
        raise GuardError(f"{what} is not a commit hash")
    return sha


def _repo(value: Any, what: str) -> str:
    repo = _str(value, what)
    if not _REPO.fullmatch(repo):
        raise GuardError(f"{what} is not owner/name")
    return repo


def _pull_request(raw: Any, number: int) -> tuple[rules.PullRequest, str, int]:
    if not isinstance(raw, dict):
        raise GuardError("pull request is not an object")
    user = raw.get("user")
    if not isinstance(user, dict):
        raise GuardError("pull request has no author")
    head, base = raw.get("head"), raw.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise GuardError("pull request has no head or base")
    head_repo = head.get("repo")
    if not isinstance(head_repo, dict):
        raise GuardError("pull request head repository is gone")
    base_repo = base.get("repo")
    if not isinstance(base_repo, dict):
        raise GuardError("pull request base repository is missing")
    pr = rules.PullRequest(
        number=number,
        author_id=_int(user.get("id"), "author id"),
        base_repo=_repo(base_repo.get("full_name"), "base repository"),
        head_repo=_repo(head_repo.get("full_name"), "head repository"),
        head_ref=_str(head.get("ref"), "head ref"),
        head_sha=_sha(head.get("sha"), "head sha"),
    )
    return pr, _sha(base.get("sha"), "base sha"), _int(raw.get("changed_files"), "changed_files")


def _files(api: Api, repo: str, number: int, expected: int) -> list[rules.ChangedFile]:
    if expected >= GITHUB_FILE_LIST_LIMIT:
        raise GuardError(
            f"{expected} changed files: at or over GitHub's {GITHUB_FILE_LIST_LIMIT} limit"
        )
    files: list[rules.ChangedFile] = []
    for raw in api.get_pages(f"/repos/{repo}/pulls/{number}/files"):
        if not isinstance(raw, dict):
            raise GuardError("changed file is not an object")
        patch = raw.get("patch")
        previous = raw.get("previous_filename")
        files.append(
            rules.ChangedFile(
                path=_str(raw.get("filename"), "filename"),
                status=_str(raw.get("status"), "status"),
                patch=patch if isinstance(patch, str) else None,
                previous_path=previous if isinstance(previous, str) else None,
            )
        )
    if len(files) != expected:
        raise GuardError(f"file list truncated: got {len(files)} of {expected}")
    return files


def _reviews(api: Api, repo: str, number: int) -> list[rules.Review]:
    reviews: list[rules.Review] = []
    for raw in api.get_pages(f"/repos/{repo}/pulls/{number}/reviews"):
        if not isinstance(raw, dict):
            raise GuardError("review is not an object")
        user = raw.get("user")
        if not isinstance(user, dict):  # a deleted account can't be the owner
            continue
        reviews.append(
            rules.Review(
                user_id=_int(user.get("id"), "reviewer id"),
                state=_str(raw.get("state"), "review state"),
                commit_id=_str(raw.get("commit_id"), "review commit"),
            )
        )
    return reviews


def _symlinks(api: Api, repo: str, sha: str) -> set[str]:
    tree = api.get_json(f"/repos/{repo}/git/trees/{sha}?recursive=1")
    if not isinstance(tree, dict) or tree.get("truncated") is not False:
        raise GuardError(f"tree of {sha[:7]} truncated or unreadable")
    entries = tree.get("tree")
    if not isinstance(entries, list):
        raise GuardError("tree has no entries")
    return {
        _str(e.get("path"), "tree path")
        for e in entries
        if isinstance(e, dict) and e.get("mode") == "120000"
    }


def collect(
    api: Api, repo: str, number: int
) -> tuple[rules.PullRequest, list[rules.ChangedFile], list[rules.Review], rules.Snapshot]:
    """Everything `rules.evaluate` needs, or GuardError."""
    pr, base_sha, expected = _pull_request(api.get_json(f"/repos/{repo}/pulls/{number}"), number)
    files = _files(api, repo, number, expected)
    reviews = _reviews(api, repo, number)

    compare = api.get_json(f"/repos/{pr.base_repo}/compare/{base_sha}...{pr.head_sha}")
    merge_base = _sha(
        (compare.get("merge_base_commit") or {}).get("sha") if isinstance(compare, dict) else None,
        "merge base",
    )
    symlinks = _symlinks(api, pr.base_repo, merge_base) | _symlinks(api, pr.head_repo, pr.head_sha)

    changed = {f.path for f in files}

    def contents(name: str) -> tuple[str | None, str | None]:
        if name not in changed:
            return None, None
        return (
            api.get_text(f"/repos/{pr.base_repo}/contents/{name}?ref={merge_base}"),
            api.get_text(f"/repos/{pr.head_repo}/contents/{name}?ref={pr.head_sha}"),
        )

    pyproject_base, pyproject_head = contents("pyproject.toml")
    lock_base, lock_head = contents("uv.lock")
    snapshot = rules.Snapshot(
        pyproject_base=pyproject_base,
        pyproject_head=pyproject_head,
        lock_base=lock_base,
        lock_head=lock_head,
        symlinks=frozenset(symlinks),
    )
    return pr, files, reviews, snapshot
