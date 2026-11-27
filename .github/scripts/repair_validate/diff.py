"""Turn the three outputs of a diff into per-file changes, refusing anything incomplete.

The inputs are `diff --raw -z`, `diff --numstat -z` and a zero-context unified patch, all
produced with renames disabled (a rename is then a delete plus an add, and each side is checked
on its own). The raw output carries paths and modes, which are exact. The patch carries the
added lines, parsed by counting each hunk's lines rather than by trusting `+++` headers, so a
line of content can never pass for a header. The numstat output is a second opinion: if the
patch's counts disagree with it, the patch was truncated or tampered with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from repair_validate.errors import ValidateError

_RAW_HEAD = re.compile(r":([0-7]{6}) ([0-7]{6}) [0-9a-f]{4,64} [0-9a-f]{4,64} ([AMDT])")
_HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # A added, M modified, D deleted, T type changed
    old_mode: str  # "000000" when the file did not exist
    new_mode: str  # "000000" when the file is gone
    added: tuple[str, ...]  # the added lines, without the leading "+"
    binary: bool


def _parse_raw(raw: bytes) -> list[tuple[str, str, str, str]]:
    parts = raw.decode("utf-8", errors="surrogateescape").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2:
        raise ValidateError("raw diff output is incomplete")
    entries: list[tuple[str, str, str, str]] = []
    for head, path in zip(parts[0::2], parts[1::2], strict=True):
        match = _RAW_HEAD.fullmatch(head)
        if not match or not path:
            raise ValidateError("raw diff output is malformed")
        entries.append((match[1], match[2], match[3], path))
    return entries


def _parse_numstat(numstat: bytes) -> list[tuple[str, str, str]]:
    parts = numstat.decode("utf-8", errors="surrogateescape").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    entries: list[tuple[str, str, str]] = []
    for part in parts:
        fields = part.split("\t", 2)
        if len(fields) != 3:
            raise ValidateError("numstat output is malformed")
        entries.append((fields[0], fields[1], fields[2]))
    return entries


@dataclass
class _Block:
    added: list[str]
    removed: int = 0
    binary_marker: bool = False


def _parse_patch(patch: str) -> list[_Block]:
    lines = patch.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    elif lines:
        raise ValidateError("patch does not end with a newline: truncated")
    blocks: list[_Block] = []
    old_left = new_left = 0
    for line in lines:
        if old_left or new_left:
            marker = line[:1]
            if marker == "+" and new_left:
                new_left -= 1
                blocks[-1].added.append(line[1:])
            elif marker == "-" and old_left:
                old_left -= 1
                blocks[-1].removed += 1
            elif marker == " " and old_left and new_left:
                old_left -= 1
                new_left -= 1
            elif marker == "\\":
                pass
            else:
                raise ValidateError("patch hunk does not match its header")
        elif line.startswith("diff --git "):
            blocks.append(_Block(added=[]))
        elif not blocks:
            raise ValidateError("patch does not start with a file header")
        elif line.startswith("@@ "):
            match = _HUNK.match(line)
            if not match:
                raise ValidateError("patch hunk header is malformed")
            old_left = int(match[1]) if match[1] is not None else 1
            new_left = int(match[2]) if match[2] is not None else 1
        elif line.startswith(("Binary files ", "GIT binary patch")):
            blocks[-1].binary_marker = True
    if old_left or new_left:
        raise ValidateError("patch ends inside a hunk: truncated")
    return blocks


def parse_diff(raw: bytes, numstat: bytes, patch: str) -> list[FileChange]:
    """The changes, or ValidateError if the three views don't describe the same complete diff."""
    entries = _parse_raw(raw)
    stats = _parse_numstat(numstat)
    blocks = _parse_patch(patch)
    if not (len(entries) == len(stats) == len(blocks)):
        raise ValidateError(
            f"diff views disagree: {len(entries)} raw, {len(stats)} numstat, {len(blocks)} patch"
        )
    changes: list[FileChange] = []
    for (old_mode, new_mode, status, path), (plus, minus, stat_path), block in zip(
        entries, stats, blocks, strict=True
    ):
        if stat_path != path:
            raise ValidateError("diff views list different paths")
        binary = plus == "-" and minus == "-"
        if binary:
            if block.added or block.removed:
                raise ValidateError("binary file has text hunks")
        elif not (plus.isdigit() and minus.isdigit()) or (
            int(plus) != len(block.added) or int(minus) != block.removed
        ):
            raise ValidateError(f"patch for {path!r} disagrees with numstat: truncated")
        changes.append(
            FileChange(
                path=path,
                status=status,
                old_mode=old_mode,
                new_mode=new_mode,
                added=tuple(block.added),
                binary=binary or block.binary_marker,
            )
        )
    return changes
