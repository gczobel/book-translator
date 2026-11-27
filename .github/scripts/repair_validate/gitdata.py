"""Read a repair's commits out of a git object store, as data.

Only plumbing that reads objects is used: no checkout, no merge, no apply, no hooks, no filters
and no external diff or textconv drivers. The patch under review is never turned into files on
disk, so nothing in it can run. Every failure to read (a non-zero exit, a shallow history, output
over the size limits) raises ValidateError so the caller fails closed.
"""

from __future__ import annotations

import os
import re
import subprocess

from repair_validate.errors import ValidateError

MAX_PATCH_BYTES = 4_000_000
MAX_BLOB_BYTES = 2_000_000
_SHA = re.compile(r"[0-9a-f]{40}")
_DIFF_OPTIONS = [
    "--no-renames",
    "--no-textconv",
    "--no-ext-diff",
    "--no-color",
    "--submodule=short",
    "--full-index",
]
_REGULAR_MODES = {"100644", "100755"}


def _require_sha(sha: str) -> str:
    if not _SHA.fullmatch(sha):
        raise ValidateError("not a full commit hash")
    return sha


class GitTree:
    """The files of one commit, read lazily from the object store."""

    def __init__(self, repo: GitRepo, entries: dict[str, tuple[str, str]]) -> None:
        self._repo = repo
        self._entries = entries

    def paths(self) -> list[str]:
        return list(self._entries)

    def read(self, path: str) -> str:
        mode, oid = self._entries[path]
        if mode not in _REGULAR_MODES:
            raise ValidateError(f"{path} is a link or submodule, not a regular file")
        data = self._repo.run(["cat-file", "blob", oid], limit=MAX_BLOB_BYTES)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValidateError(f"{path} is not valid UTF-8") from error


class GitRepo:
    def __init__(self, directory: str, *, max_patch_bytes: int = MAX_PATCH_BYTES) -> None:
        self.directory = directory
        self.max_patch_bytes = max_patch_bytes

    def _exec(self, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "/nonexistent",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
        try:
            return subprocess.run(
                ["git", "-c", "core.fsmonitor=false", *args],
                cwd=self.directory,
                env=env,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValidateError(f"cannot run git: {error}") from error

    def run(self, args: list[str], *, limit: int | None = None) -> bytes:
        done = self._exec(args)
        if done.returncode != 0:
            raise ValidateError(f"git {args[0]} failed with exit {done.returncode}")
        if limit is not None and len(done.stdout) > limit:
            raise ValidateError(f"git {args[0]} output is over {limit} bytes: refusing to truncate")
        return done.stdout

    def is_shallow(self) -> bool:
        out = self.run(["rev-parse", "--is-shallow-repository"]).strip()
        if out not in (b"true", b"false"):
            raise ValidateError("cannot tell whether the history is shallow")
        return out == b"true"

    def require_commit(self, sha: str) -> None:
        if self.run(["cat-file", "-t", _require_sha(sha)]).strip() != b"commit":
            raise ValidateError(f"{sha[:7]} is not a commit")

    def is_ancestor(self, base: str, head: str) -> bool:
        done = self._exec(["merge-base", "--is-ancestor", _require_sha(base), _require_sha(head)])
        if done.returncode not in (0, 1):
            raise ValidateError(f"cannot tell whether head descends from base: {done.returncode}")
        return done.returncode == 0

    def _diff(self, mode: list[str], base: str, head: str) -> bytes:
        return self.run(
            ["diff", *mode, *_DIFF_OPTIONS, _require_sha(base), _require_sha(head), "--"],
            limit=self.max_patch_bytes,
        )

    def raw_diff(self, base: str, head: str) -> bytes:
        return self._diff(["--raw", "-z"], base, head)

    def numstat(self, base: str, head: str) -> bytes:
        return self._diff(["--numstat", "-z"], base, head)

    def patch(self, base: str, head: str) -> str:
        return self._diff(["-U0"], base, head).decode("utf-8", errors="replace")

    def tree(self, sha: str) -> GitTree:
        out = self.run(
            ["ls-tree", "-r", "-z", "--full-tree", _require_sha(sha)], limit=self.max_patch_bytes
        )
        entries: dict[str, tuple[str, str]] = {}
        for record in out.decode("utf-8", errors="surrogateescape").split("\0"):
            if not record:
                continue
            meta, tab, path = record.partition("\t")
            fields = meta.split(" ")
            if not tab or len(fields) != 3 or not _SHA.fullmatch(fields[2]):
                raise ValidateError("tree listing is malformed")
            entries[path] = (fields[0], fields[2])
        return GitTree(self, entries)
