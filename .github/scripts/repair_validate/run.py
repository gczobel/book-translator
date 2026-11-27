"""The validator's entry point: read the environment, decide, print, return an exit code.

Inputs, all from the environment: REPAIR_BASE (the commit the repair started from),
REPAIR_HEAD (the commit the agent produced) and optionally REPAIR_DIR (a repository holding
both objects; default the current directory). Exit 0 means the patch may be applied, 1 that it
was rejected, 2 that it could not be judged. Every failure to decide is exit 2: fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol

from repair_validate import ratchet, rules
from repair_validate.diff import parse_diff
from repair_validate.errors import ValidateError
from repair_validate.gitdata import GitRepo

_SHA = re.compile(r"[0-9a-f]{40}")


class Repo(Protocol):
    def is_shallow(self) -> bool: ...
    def require_commit(self, sha: str) -> None: ...
    def is_ancestor(self, base: str, head: str) -> bool: ...
    def raw_diff(self, base: str, head: str) -> bytes: ...
    def numstat(self, base: str, head: str) -> bytes: ...
    def patch(self, base: str, head: str) -> str: ...
    def tree(self, sha: str) -> ratchet.Tree: ...


def _require_sha(value: str, name: str) -> str:
    if not _SHA.fullmatch(value):
        raise ValidateError(f"{name} is missing or not a full commit hash")
    return value


def validate(repo: Repo, base: str, head: str) -> list[str]:
    """Every reason to reject the patch from base to head; empty if acceptable."""
    if repo.is_shallow():
        raise ValidateError("history is shallow: cannot be sure the diff is complete")
    repo.require_commit(base)
    repo.require_commit(head)
    if not repo.is_ancestor(base, head):
        raise ValidateError("head does not descend from base")
    changes = parse_diff(
        repo.raw_diff(base, head), repo.numstat(base, head), repo.patch(base, head)
    )
    base_tree, head_tree = repo.tree(base), repo.tree(head)

    def pyproject(tree: ratchet.Tree) -> str | None:
        return tree.read("pyproject.toml") if "pyproject.toml" in tree.paths() else None

    reasons = rules.evaluate(changes, pyproject(base_tree), pyproject(head_tree))
    if reasons:
        return reasons
    return ratchet.check(base_tree, head_tree)


def run(env: Mapping[str, str], repo: Repo | None = None) -> int:
    try:
        base = _require_sha(env.get("REPAIR_BASE", ""), "REPAIR_BASE")
        head = _require_sha(env.get("REPAIR_HEAD", ""), "REPAIR_HEAD")
        if repo is None:
            repo = GitRepo(env.get("REPAIR_DIR") or ".")
        reasons = validate(repo, base, head)
    except ValidateError as error:
        print(f"repair-validate: cannot decide, failing closed: {error}")
        return 2
    except Exception as error:  # anything unexpected must still fail the check
        print(f"repair-validate: unexpected {type(error).__name__}, failing closed")
        return 2

    if reasons:
        for reason in reasons:
            print(f"  rejected: {reason}")
        print(f"repair-validate: REJECTED, {len(reasons)} problem(s)")
        return 1
    print("repair-validate: passed")
    return 0
