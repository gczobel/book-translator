"""Entry point: compare two lock files, publish the verdict, exit non-zero unless it is a pass."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from lockage.core import LockError, Policy, changed_entries, check, minimum_age, parse_lock
from lockage.pypi import PyPiClient


def run(
    env: Mapping[str, str], client: PyPiClient | None = None, now: datetime | None = None
) -> int:
    """0 only if every changed lock entry is old enough. Anything else, including bad input, is 1.

    Inputs (environment): BASE_LOCK and HEAD_LOCK are paths to the `uv.lock` of the base and
    head; IS_SECURITY and URGENT are exactly "true" or "false". The caller reads `urgent` from a
    label the owner applied. The verdict is also written to $GITHUB_OUTPUT as `passed`, and a
    step that crashes leaves it empty, which callers must treat as not passed.
    """
    passed = False
    try:
        policy = Policy(security=_flag(env, "IS_SECURITY"), urgent=_flag(env, "URGENT"))
        base = parse_lock(_read(env, "BASE_LOCK"))
        head = parse_lock(_read(env, "HEAD_LOCK"))
        entries = changed_entries(base, head)
        client = client or PyPiClient()
        problems = check(entries, minimum_age(policy), now or datetime.now(UTC), client.upload_time)
    except LockError as error:
        problems = [str(error)]
    except Exception as error:
        problems = [f"unexpected {type(error).__name__}"]
    else:
        passed = not problems
        print(f"lockage: checked {len(entries)} changed lock entries")
    for problem in problems:
        print(f"lockage: FAILED: {problem}")
    wrote = _publish(env, passed)
    return 0 if passed and wrote else 1


def _flag(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name)
    if value not in ("true", "false"):
        raise LockError(f"{name} must be 'true' or 'false'")
    return value == "true"


def _read(env: Mapping[str, str], name: str) -> str:
    path = env.get(name)
    if not path:
        raise LockError(f"{name} is not set")
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LockError(f"cannot read the lock file in {name}") from error


def _publish(env: Mapping[str, str], passed: bool) -> bool:
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return True  # the exit code still carries the verdict
    try:
        with open(path, "a", encoding="utf-8") as out:
            out.write(f"passed={str(passed).lower()}\n")
    except OSError:
        print("lockage: cannot write the step outputs")
        return False
    return True
