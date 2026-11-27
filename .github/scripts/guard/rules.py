"""Decision rules for the `guard` check (ADR 0005).

Pure functions over plain data: no network, no files, no environment. That keeps the
rules testable and lets `collect.py` own every way an input can be missing or truncated.

A pull request that touches a guarded path passes only if the owner approved the head
commit (by numeric user ID), or the owner wrote it, or it is a Dependabot pin bump in a
workflow file that touches no secret-handling action. Everything else about it is
irrelevant: this check never reads PR text, only structured data.
"""

from __future__ import annotations

import json
import re
import tomllib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ghapi.identities import DEPENDABOT_ID, OWNER_ID

# Actions that handle secrets: bumping them always needs the owner (ADR 0005, "Pinning").
SECRET_HANDLING_ACTIONS = frozenset(
    {
        "actions/create-github-app-token",
        "anthropics/claude-code-action",
        "googleapis/release-please-action",
        "dependabot/fetch-metadata",
    }
)


def _under(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(prefix)}(?:/.*)?")


def _anywhere_dir(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?:.*/)?{re.escape(name)}(?:/.*)?")


def _anywhere_file(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?:.*/)?{re.escape(name)}")


def _root_file(name: str) -> re.Pattern[str]:
    return re.compile(re.escape(name))


# Lower-case: paths are casefolded before matching, because checkouts on case-insensitive
# filesystems would treat `Agents.md` as `AGENTS.md`.
_GUARDED = (
    _under(".github"),  # workflows, Dependabot config, CI scripts (including this guard)
    _anywhere_dir(".claude"),
    _anywhere_file("review.md"),
    _root_file("agents.md"),
    _root_file("claude.md"),
    _under("docs/agents"),
    _under("docs/adr"),
    _root_file(".mcp.json"),
    _root_file("release-please-config.json"),
    _root_file(".release-please-manifest.json"),
    _root_file(".gitattributes"),
    _root_file(".gitmodules"),
    _root_file(".python-version"),
    _root_file("uv.toml"),  # [tool.uv] by another name
)


def _quote(path: str) -> str:
    """A path safe to print in a CI log: JSON-escaped, so it can't start a workflow command."""
    return json.dumps(path)


def _normalise(path: str) -> str:
    return unicodedata.normalize("NFKC", path).casefold()


def is_guarded_path(path: str) -> bool:
    """True if a change to `path` needs the owner. Malformed paths count as guarded."""
    if not path or path.startswith("/") or "\\" in path:
        return True
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return True
    normalised = _normalise(path)
    return any(p.fullmatch(normalised) for p in _GUARDED)


# --- Dependabot pin updates --------------------------------------------------------------

_USES = re.compile(
    r"(?P<pre>\s*(?:-\s+)?uses:\s+)"
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?)"
    r"@(?P<sha>[0-9a-f]{40})"
    r"(?P<comment>[ \t]+#[ \t]*[\w.+\-/ ]*)?"
)


def _is_pin_bump(old: str, new: str) -> str | None:
    """The action repo if `old` -> `new` changes only the hash and the version comment."""
    a, b = _USES.fullmatch(old), _USES.fullmatch(new)
    if a is None or b is None:
        return None
    if a["pre"] != b["pre"] or a["repo"] != b["repo"]:
        return None
    return a["repo"]


def pin_update_repos(patch: str | None) -> frozenset[str] | None:
    """The actions bumped by `patch`, or None unless every changed line is a pin bump."""
    if not patch:
        return None
    repos: set[str] = set()
    removed: list[str] = []
    added: list[str] = []

    def flush() -> bool:
        if len(removed) != len(added):
            return False
        for old, new in zip(removed, added, strict=True):
            repo = _is_pin_bump(old, new)
            if repo is None:
                return False
            repos.add(repo)
        removed.clear()
        added.clear()
        return True

    for line in patch.split("\n"):
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("\\"):
            return None
        else:  # context line or hunk header ends a block of changes
            if not flush():
                return None
    if not flush() or not repos:
        return None
    return frozenset(repos)


# --- uv configuration and lock sources ---------------------------------------------------


def _toml(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    return tomllib.loads(text)


def uv_config_changed(base: str | None, head: str | None) -> bool:
    """True if `[tool.uv]` or `[build-system]` differ between base and head."""
    if base is None and head is None:
        return False
    try:
        b, h = _toml(base), _toml(head)
    except tomllib.TOMLDecodeError:
        return True
    if b is None or h is None:
        return True
    return b.get("tool", {}).get("uv") != h.get("tool", {}).get("uv") or b.get(
        "build-system"
    ) != h.get("build-system")


_DIRECT_KEYS = ("git", "url", "path", "directory", "editable", "registry", "index", "virtual")


def _lock_origins(lock: dict[str, Any]) -> tuple[set[tuple[str, Any]], set[tuple[str, str]]]:
    """Where the lock says packages come from, and the hosts that artifacts download from."""
    sources: set[tuple[str, Any]] = set()
    hosts: set[tuple[str, str]] = set()

    def add_host(url: Any) -> None:
        parts = urlsplit(str(url))
        hosts.add((parts.scheme, parts.netloc))

    def walk_direct(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _DIRECT_KEYS:
                    sources.add((key, str(value)))
                else:
                    walk_direct(value)
        elif isinstance(node, list):
            for item in node:
                walk_direct(item)

    for pkg in lock.get("package", []):
        for key, value in (pkg.get("source") or {}).items():
            sources.add((key, str(value)))
        sdist = pkg.get("sdist")
        if sdist and "url" in sdist:
            add_host(sdist["url"])
        for wheel in pkg.get("wheels", []):
            if "url" in wheel:
                add_host(wheel["url"])
        walk_direct(pkg.get("metadata", {}))
    return sources, hosts


def lock_sources_changed(base: str | None, head: str | None) -> bool:
    """True if the head lock names a package source or download host the base lock didn't."""
    if base is None and head is None:
        return False
    try:
        b, h = _toml(base), _toml(head)
    except tomllib.TOMLDecodeError:
        return True
    if b is None or h is None:
        return True
    b_sources, b_hosts = _lock_origins(b)
    h_sources, h_hosts = _lock_origins(h)
    return not (h_sources <= b_sources and h_hosts <= b_hosts)


# --- the decision ------------------------------------------------------------------------


@dataclass(frozen=True)
class PullRequest:
    number: int
    author_id: int
    base_repo: str
    head_repo: str
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    patch: str | None
    previous_path: str | None = None


@dataclass(frozen=True)
class Review:
    user_id: int
    state: str
    commit_id: str


@dataclass(frozen=True)
class Snapshot:
    """File contents and symlinks the decision needs, read at the merge base and the head."""

    pyproject_base: str | None
    pyproject_head: str | None
    lock_base: str | None
    lock_head: str | None
    symlinks: frozenset[str]


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[str, ...] = field(default=())  # why the PR is guarded
    detail: str = ""  # how it passed despite being guarded, or what it is waiting for


def _action_key(repo: str) -> str:
    """`owner/name` of an action, lower-cased: subpaths and case can't dodge the list."""
    return "/".join(_normalise(repo).split("/")[:2])


_WORKFLOW = re.compile(r"\.github/workflows/[^/]+\.ya?ml")


def _same_repo(pr: PullRequest) -> bool:
    return pr.head_repo == pr.base_repo


def _is_exempt_dependabot_bump(pr: PullRequest, f: ChangedFile) -> bool:
    if pr.author_id != DEPENDABOT_ID or not _same_repo(pr):
        return False
    if not pr.head_ref.startswith("dependabot/"):
        return False
    if f.status != "modified" or f.previous_path or not _WORKFLOW.fullmatch(f.path):
        return False
    repos = pin_update_repos(f.patch)
    if repos is None:
        return False
    return not {_action_key(r) for r in repos} & SECRET_HANDLING_ACTIONS


def _owner_approved(pr: PullRequest, reviews: Iterable[Review]) -> bool:
    latest: Review | None = None
    for review in reviews:
        if review.user_id == OWNER_ID and review.state in {
            "APPROVED",
            "CHANGES_REQUESTED",
            "DISMISSED",
        }:
            latest = review
    return latest is not None and latest.state == "APPROVED" and latest.commit_id == pr.head_sha


def evaluate(
    pr: PullRequest,
    files: Sequence[ChangedFile],
    reviews: Sequence[Review],
    snapshot: Snapshot,
) -> Verdict:
    """Decide whether the PR may merge as far as the guard is concerned."""
    reasons: list[str] = []
    changed = {f.path for f in files}
    for f in files:
        paths = [f.path, *([f.previous_path] if f.previous_path else [])]
        guarded = [p for p in paths if is_guarded_path(p)]
        if guarded and not _is_exempt_dependabot_bump(pr, f):
            reasons += [f"guarded path {_quote(p)}" for p in guarded]
        reasons += [f"symlink {_quote(p)}" for p in paths if p in snapshot.symlinks]
    if "pyproject.toml" in changed and uv_config_changed(
        snapshot.pyproject_base, snapshot.pyproject_head
    ):
        reasons.append("[tool.uv] or [build-system] changed in pyproject.toml")
    if "uv.lock" in changed and lock_sources_changed(snapshot.lock_base, snapshot.lock_head):
        reasons.append("uv.lock names a new package source or download host")

    if not reasons:
        return Verdict(passed=True)
    if _owner_approved(pr, reviews):
        return Verdict(True, tuple(reasons), "the owner approved the head commit")
    if pr.author_id == OWNER_ID and _same_repo(pr):
        return Verdict(True, tuple(reasons), "the owner wrote it (they can't approve their own)")
    return Verdict(False, tuple(reasons), "waiting for the owner's approval of the head commit")
