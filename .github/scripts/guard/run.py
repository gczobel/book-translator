"""The guard's entry point: read the environment, decide, print, return an exit code."""

from __future__ import annotations

import re
from collections.abc import Mapping

from guard import rules
from guard.api import HttpApi
from guard.collect import Api, GuardError, collect

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def run(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 if the PR may merge as far as the guard is concerned, non-zero otherwise.

    Every failure to decide is a non-zero exit: the check fails closed.
    """
    try:
        repo = env.get("GUARD_REPO", "")
        number_text = env.get("GUARD_PR", "")
        if not _REPO.fullmatch(repo) or not re.fullmatch(r"[0-9]+", number_text):
            raise GuardError("GUARD_REPO or GUARD_PR is missing or malformed")
        if api is None:
            token = env.get("GH_TOKEN", "")
            if not token:
                raise GuardError("GH_TOKEN is missing")
            api = HttpApi(token)
        pr, files, reviews, snapshot = collect(api, repo, int(number_text))
        verdict = rules.evaluate(pr, files, reviews, snapshot)
    except GuardError as error:
        print(f"guard: cannot decide, failing closed: {error}")
        return 2
    except Exception as error:  # anything unexpected must still fail the check
        print(f"guard: unexpected {type(error).__name__}, failing closed")
        return 2

    for reason in verdict.reasons:
        print(f"  guarded: {reason}")
    if verdict.passed:
        suffix = f" ({verdict.satisfied_by})" if verdict.satisfied_by else ""
        print(f"guard: passed{suffix}")
        return 0
    print(f"guard: FAILED, {verdict.satisfied_by}")
    return 1
