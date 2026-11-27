"""What a repair patch may touch and may not add (ADR 0005, issue #21).

Pure functions over data: the parsed changes and the two versions of pyproject.toml. They
return every violation found, as human-readable reasons; an empty list means acceptable.
Everything not explicitly allowed is a violation.

Allowed: files under `src/**` that are not test support, and dependency lines in
`pyproject.toml` and `uv.lock`. A repair may not weaken the checks that judge it, so tests,
fixtures, recorded answers, tool configuration, agent and CI configuration, links, binaries,
new lint or type suppressions and secret-looking strings are all refused.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Iterable
from typing import Any

from repair_validate.diff import FileChange

REGULAR = "100644"
ABSENT = "000000"

# A path component that marks agent or CI configuration, wherever it sits.
_CONFIG_DIRS = {".git", ".github", ".claude"}
# A path component that marks tests, fixtures or recorded answers, wherever it sits under src.
_TEST_SUPPORT_DIRS = {
    "tests",
    "test",
    "fixtures",
    "fixture",
    "cassettes",
    "cassette",
    "recorded",
    "recordings",
    "recording",
    "snapshots",
    "__snapshots__",
    "golden",
    "testdata",
}
_TEST_FILE = re.compile(r"conftest\.py|test_.*\.py|.*_test\.py")

_SUPPRESSIONS = re.compile(
    r"#\s*noqa"
    r"|ruff:\s*(noqa|disable)"
    r"|type:\s*ignore"
    r"|\b(pyright|mypy|pyrefly|ty):\s*ignore"
    r"|pylint:\s*disable"
    r"|pragma:\s*no\s*cover"
    r"|fmt:\s*(off|skip)",
    re.IGNORECASE,
)

_SECRET_PREFIXES = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
    r"|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_LONG_HEX = re.compile(r"[0-9a-fA-F]{32,}")
_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
_ENTROPY_BITS = 4.0

_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_URL = r'"https://files\.pythonhosted\.org/packages/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}/[A-Za-z0-9._+-]+"'
_FILE = (
    rf'url = {_URL}, hash = "sha256:[0-9a-f]{{64}}", size = [0-9]+(, upload-time = "[0-9TZ:.-]+")?'
)
_LOCK_LINES = re.compile(
    "|".join(
        [
            r"",
            r"\[\[package\]\]",
            r"\[package\.(optional-dependencies|dev-dependencies|metadata|metadata\.requires-dev)\]",
            rf'name = "{_NAME}"',
            r'version = "[0-9A-Za-z.+!_-]+"',
            r'source = \{ registry = "https://pypi\.org/simple" \}',
            r'source = \{ (editable|virtual) = "\." \}',
            rf"sdist = \{{ {_FILE} \}}",
            rf"\s+\{{ {_FILE} \}},",
            r"(wheels|dependencies|resolution-markers|requires-dist|requires-dev) = \[",
            rf"{_NAME} = \[",
            r"\]",
            r'\s+"[^"\n]*",',
            r'\s+\{ name = "' + _NAME + r'"(, [a-z-]+ = ("[^"\n]*"|\[[^\]\n]*\]))* \},',
            r"provides-extras = \[[^\]\n]*\]",
        ]
    )
)

_REQUIREMENT = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*\s*(\[[A-Za-z0-9._,\s-]+\])?\s*"
    r"(\(?\s*[<>=!~]=?[A-Za-z0-9.*+!_-]+(\s*,\s*[<>=!~]=?[A-Za-z0-9.*+!_-]+)*\s*\)?)?\s*"
    r"(;[^@\n]*)?"
)


def _entropy(text: str) -> float:
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def _looks_secret(line: str) -> bool:
    if _SECRET_PREFIXES.search(line) or _LONG_HEX.search(line):
        return True
    for token in _TOKEN.findall(line):
        has_digit = any(c.isdigit() for c in token)
        has_letter = any(c.isalpha() for c in token)
        if has_digit and has_letter and _entropy(token) >= _ENTROPY_BITS:
            return True
    return False


def _path_problem(path: str) -> str | None:
    """Why the path may not be touched, or None if it may be."""
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in parts):
        return "unsafe path"
    if any(p.lower() in _CONFIG_DIRS for p in parts):
        return "agent or CI configuration"
    if path in ("pyproject.toml", "uv.lock"):
        return None
    if parts[0] != "src" or len(parts) < 2:
        return "outside src/** and the dependency files"
    if any(p.lower() in _TEST_SUPPORT_DIRS for p in parts[1:-1]) or _TEST_FILE.fullmatch(parts[-1]):
        return "tests, fixtures or recorded answers"
    return None


def _mode_problem(change: FileChange) -> str | None:
    if change.status == "D":
        return None if change.old_mode == REGULAR else "removes a symlink, submodule or odd mode"
    if change.new_mode != REGULAR or change.old_mode not in (REGULAR, ABSENT):
        return f"symlink, submodule or mode change ({change.old_mode} to {change.new_mode})"
    return None


def _lock_line_problem(line: str) -> str | None:
    if not _LOCK_LINES.fullmatch(line):
        return "not a dependency line"
    if _looks_secret(
        re.sub(
            r"https://files\.pythonhosted\.org/packages/[0-9a-f/]+|sha256:[0-9a-f]{64}", "", line
        )
    ):
        return "high-entropy string"
    return None


def _requirement_problems(head: dict[str, Any], base: dict[str, Any]) -> list[str]:
    def entries(doc: dict[str, Any]) -> list[Any]:
        project = doc.get("project", {})
        found: list[Any] = list(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            found.extend(group)
        for group in doc.get("dependency-groups", {}).values():
            found.extend(group)
        return found

    known = {e for e in entries(base) if isinstance(e, str)}
    problems = []
    for entry in entries(head):
        if isinstance(entry, dict) and set(entry) == {"include-group"}:
            continue
        if not isinstance(entry, str):
            problems.append(f"unexpected dependency entry {entry!r}")
        elif entry not in known and (
            not _REQUIREMENT.fullmatch(entry) or "://" in entry or "@" in entry
        ):
            problems.append(f"dependency {entry!r} is not a plain version requirement")
    return problems


def _strip_dependencies(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out.pop("dependency-groups", None)
    project = out.get("project")
    if isinstance(project, dict):
        project = {
            k: v for k, v in project.items() if k not in ("dependencies", "optional-dependencies")
        }
        out["project"] = project
    return out


def _pyproject_problems(base: str | None, head: str | None) -> list[str]:
    if base is None or head is None:
        return ["pyproject.toml is added or deleted"]
    try:
        base_doc, head_doc = tomllib.loads(base), tomllib.loads(head)
        base_rest, head_rest = _strip_dependencies(base_doc), _strip_dependencies(head_doc)
        problems = []
        if base_rest != head_rest:
            keys = sorted(
                k
                for k in base_rest.keys() | head_rest.keys()
                if base_rest.get(k) != head_rest.get(k)
            )
            problems.append(f"pyproject.toml changes outside dependency lines: {', '.join(keys)}")
        return problems + _requirement_problems(head_doc, base_doc)
    except (tomllib.TOMLDecodeError, AttributeError, TypeError) as error:
        return [f"pyproject.toml cannot be read as a plain dependency edit: {error}"]


def evaluate(
    changes: Iterable[FileChange], pyproject_base: str | None, pyproject_head: str | None
) -> list[str]:
    """Every reason the patch must be rejected; empty if it may be applied."""
    reasons: list[str] = []
    seen = False
    for change in changes:
        seen = True
        path = change.path
        problem = _path_problem(path) or _mode_problem(change)
        if problem:
            reasons.append(f"{path}: {problem}")
            continue
        if change.binary:
            reasons.append(f"{path}: binary change")
            continue
        if path == "uv.lock":
            if change.status != "M":
                reasons.append(f"{path}: added or deleted")
            for line in change.added:
                if (why := _lock_line_problem(line)) is not None:
                    reasons.append(f"{path}: {why}: {line[:60]!r}")
            continue
        if path == "pyproject.toml":
            reasons.extend(_pyproject_problems(pyproject_base, pyproject_head))
        for line in change.added:
            if _SUPPRESSIONS.search(line):
                reasons.append(f"{path}: new lint, type or coverage suppression: {line[:60]!r}")
            if _looks_secret(line):
                reasons.append(f"{path}: high-entropy string in an added line")
    if not seen:
        reasons.append("the patch changes nothing")
    return reasons
