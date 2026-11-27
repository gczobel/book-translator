"""Turn the agent's patch text into a commit, as data.

The patch is applied to a temporary index only (`git apply --cached`): nothing is checked out,
no hook, filter or driver runs, and no file is written outside the object store, so a hostile
patch cannot do more than fail. The resulting commit is judged by `repair_validate` (which reads
objects only) and later replayed by the push job through GitHub's own commit API.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

_SHA = re.compile(r"[0-9a-f]{40}")
MAX_PATCH_BYTES = 90_000  # its base64 must fit the 128 KB limit on one environment variable


class PatchError(Exception):
    """The patch can't be turned into a commit. Callers fail closed."""


def _git(
    directory: str, args: list[str], *, index: str | None = None, data: bytes | None = None
) -> bytes:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "book-translator-repair",
        "GIT_AUTHOR_EMAIL": "repair@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "book-translator-repair",
        "GIT_COMMITTER_EMAIL": "repair@users.noreply.github.com",
        "LC_ALL": "C",
    }
    if index:
        env["GIT_INDEX_FILE"] = index
    try:
        done = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false", *args],
            cwd=directory,
            env=env,
            input=data,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PatchError(f"cannot run git: {error}") from error
    if done.returncode != 0:
        raise PatchError(f"git {args[0]} failed with exit {done.returncode}")
    return done.stdout


def _sha(value: str) -> str:
    if not _SHA.fullmatch(value):
        raise PatchError("not a full commit hash")
    return value


def build_commit(directory: str, base: str, patch: str, message: str) -> tuple[str, str]:
    """`(commit, tree)` of `base` plus the patch. Refuses an empty, oversized or bad patch."""
    base = _sha(base)
    data = patch.encode("utf-8")
    if not data.strip():
        raise PatchError("the patch is empty")
    if len(data) > MAX_PATCH_BYTES:
        raise PatchError("the patch is over the size limit")
    with tempfile.TemporaryDirectory() as scratch:
        index = os.path.join(scratch, "index")
        _git(directory, ["read-tree", base], index=index)
        _git(directory, ["apply", "--cached", "--whitespace=nowarn", "-"], index=index, data=data)
        tree = _git(directory, ["write-tree"], index=index).decode().strip()
    commit = _git(directory, ["commit-tree", _sha(tree), "-p", base, "-m", message])
    return _sha(commit.decode().strip()), tree


@dataclass
class FileChanges:
    additions: dict[str, bytes] = field(default_factory=dict)  # path -> new content
    deletions: list[str] = field(default_factory=list)


def file_changes(directory: str, base: str, head: str) -> FileChanges:
    """What turns `base` into `head`, as whole-file contents (the commit API takes no diffs)."""
    raw = _git(
        directory,
        ["diff-tree", "-r", "-z", "--no-renames", "--no-textconv", "--raw", _sha(base), _sha(head)],
    )
    parts = raw.split(b"\0")
    changes = FileChanges()
    i = 0
    while i < len(parts) and parts[i]:
        meta = parts[i].decode().lstrip(":").split(" ")
        if len(meta) != 5 or i + 1 >= len(parts):
            raise PatchError("diff-tree output is malformed")
        path = parts[i + 1].decode("utf-8")
        new_mode, new_oid, status = meta[1], meta[3], meta[4]
        if status == "D":
            changes.deletions.append(path)
        elif new_mode in ("100644", "100755") and status in ("A", "M"):
            changes.additions[path] = _git(directory, ["cat-file", "blob", _sha(new_oid)])
        else:
            raise PatchError(f"{path}: not a plain file change")
        i += 2
    return changes
