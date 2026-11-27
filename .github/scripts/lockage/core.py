"""The lock-entry age gate (ADR 0005): a changed lock entry must be old enough on PyPI.

Dependabot's cooldown only sees the packages it bumps. Versions pulled in indirectly show up
only as lock-file changes, so every entry that is new or bumped in `uv.lock` is checked against
the time PyPI says it was uploaded: 7 days for a version update, 72 hours for a security update,
and none for a security update the owner labelled `urgent`.

Everything fails closed: a lock file we can't parse, an entry we can't verify against PyPI, or a
lookup that errors is a problem, never a pass.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

Entry = tuple[str, str]  # (normalised name, version)

REGISTRY = "https://pypi.org/simple"
VERSION_UPDATE_AGE = timedelta(days=7)
SECURITY_UPDATE_AGE = timedelta(hours=72)

_NAME = re.compile(r"[a-z0-9]([a-z0-9._-]*[a-z0-9])?")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!-]*")
_SEPARATORS = re.compile(r"[-_.]+")


class LockError(Exception):
    """The lock file or a PyPI answer can't be trusted. Callers fail closed."""


@dataclass(frozen=True)
class Policy:
    security: bool
    urgent: bool


def normalise(name: str) -> str:
    return _SEPARATORS.sub("-", name).lower()


def parse_lock(text: str) -> set[Entry]:
    """Every registry entry of a `uv.lock`. The project itself (editable/virtual) is skipped.

    Any other source (git, url, path, a foreign registry) can't be checked against PyPI, so it
    is an error rather than something silently let through.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise LockError("the lock file is not valid TOML") from error
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        raise LockError("the lock file lists no packages")
    entries: set[Entry] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise LockError("a lock entry is not a table")
        source = package.get("source")
        if not isinstance(source, dict):
            raise LockError("a lock entry has no source")
        if source.keys() & {"editable", "virtual"}:
            continue
        if source.get("registry") != REGISTRY:
            raise LockError("a lock entry does not come from PyPI")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise LockError("a lock entry has no name or version")
        name = normalise(name)
        if not _NAME.fullmatch(name) or not _VERSION.fullmatch(version):
            raise LockError("a lock entry has a malformed name or version")
        entries.add((name, version))
    return entries


def changed_entries(base: set[Entry], head: set[Entry]) -> set[Entry]:
    """Entries the head lock has that the base lock did not: new packages and new versions."""
    return head - base


def minimum_age(policy: Policy) -> timedelta:
    if not policy.security:
        return VERSION_UPDATE_AGE
    return timedelta(0) if policy.urgent else SECURITY_UPDATE_AGE


def check(
    entries: Iterable[Entry],
    minimum: timedelta,
    now: datetime,
    upload_time: Callable[[Entry], datetime],
) -> list[str]:
    """One message per entry that is too young or can't be verified. Empty means all clear."""
    problems: list[str] = []
    for entry in sorted(entries):
        label = f"{entry[0]} {entry[1]}"
        try:
            age = now - upload_time(entry)
        except LockError as error:
            problems.append(f"{label}: cannot verify the upload time ({error})")
            continue
        except Exception as error:
            problems.append(f"{label}: cannot verify the upload time ({type(error).__name__})")
            continue
        if age < minimum:
            problems.append(f"{label}: uploaded {_describe(age)} ago, needs {_describe(minimum)}")
    return problems


def _describe(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours}h"
