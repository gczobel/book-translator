"""Typosquat guard: a repair may not add a dependency name the PR did not already have.

`repair_validate` accepts any new plain dependency line, so an injected agent could add a
look-alike package. Names (PEP 503 normalised) are read from `pyproject.toml` requirements and
from every `[[package]]` entry of `uv.lock`, in the commit the repair started from and in the
repaired one. Any name only in the repaired one is a reason to reject. Upgrading or downgrading
a package, which Dependabot's own PR already did, adds no name.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(doc: dict[str, Any]) -> set[str]:
    project = doc.get("project", {})
    entries: list[Any] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        entries.extend(group)
    for group in doc.get("dependency-groups", {}).values():
        entries.extend(group)
    names = set()
    for entry in entries:
        if isinstance(entry, str):
            match = _NAME.match(entry)
            if match:
                names.add(normalise(match.group(1)))
    return names


def _lock_names(doc: dict[str, Any]) -> set[str]:
    return {
        normalise(p["name"])
        for p in doc.get("package", [])
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    }


def _names(pyproject: str, lock: str) -> set[str]:
    return _requirement_names(tomllib.loads(pyproject)) | _lock_names(tomllib.loads(lock))


def new_names(base_pyproject: str, head_pyproject: str, base_lock: str, head_lock: str) -> list[str]:
    """Sorted names present in the head files and absent from the base files.

    Raises tomllib.TOMLDecodeError for an unreadable file; the caller fails closed.
    """
    return sorted(
        _names(head_pyproject, head_lock) - _names(base_pyproject, base_lock),
    )
