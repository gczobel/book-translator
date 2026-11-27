"""Open or update one `ready-for-human` issue per problem.

Every input is structured: a reason code from a fixed table, a key matching a strict
pattern, optional numbers. The issue text comes from this file, never from a PR, an
issue, a log or a release note, so a stranger can't put words in the owner's inbox.

An existing issue is reused only if the maintenance App wrote it (numeric ID), it is open,
it is not a pull request, and it carries the hidden marker on a line of its own. Anyone
else's look-alike is ignored, never edited and never reopened.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ghapi.identities import MAINT_BOT_ID
from ghapi.repo import split_repo

OWNER_LOGIN = "gczobel"  # only for assigning; identity checks use numeric IDs
LABEL = "ready-for-human"

# reason code -> (title, what happened). Later tickets add their own codes here.
REASONS: dict[str, tuple[str, str]] = {
    "selftest": (
        "Escalation self-test",
        "A manual test of the escalation job. Close this issue.",
    ),
    "workflow-failed": (
        "An automation workflow failed or was cancelled",
        "A workflow that runs unattended did not finish, so something may need a human.",
    ),
    "pause-unreadable": (
        "The pause switch can't be read, so automation is paused",
        "The PAUSE repository variable could not be read. Automation stops when it can't "
        "tell whether it was paused.",
    ),
    "vulnerability-found": (
        "The daily vulnerability scan found something that needs a human",
        "The OSV scan of uv.lock found a high, critical or unknown-severity issue, a "
        "malicious-package entry, or an alert older than 48 hours with no open PR. "
        "The run log lists the packages.",
    ),
    "vulnerability-scan-failed": (
        "The daily vulnerability scan could not run or be read",
        "The OSV scan of uv.lock failed or its output could not be parsed, so nothing "
        "vulnerable can be ruled out.",
    ),
    "release-tag-unverified": (
        "A new release tag could not be verified",
        "A v* tag appeared that was not verified as release-please's merge commit on main, "
        "or the check itself failed. Do not install it until you have looked: the tag may "
        "have been created by someone else.",
    ),
}

_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_NUMBER = re.compile(r"[0-9]{1,12}")
_SERVER = "https://github.com"


class EscalationError(Exception):
    """The request is not structured as required. The job fails rather than guess."""


class Api(Protocol):
    def get_pages(self, path: str) -> list[Any]: ...

    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class Request:
    reason: str
    key: str
    ref: int | None
    run_url: str


def parse_request(env: Mapping[str, str]) -> Request:
    reason = env.get("ESCALATE_REASON", "")
    if reason not in REASONS:
        raise EscalationError("ESCALATE_REASON is not a known reason code")
    key = env.get("ESCALATE_KEY", "")
    if not _KEY.fullmatch(key):
        raise EscalationError("ESCALATE_KEY must be 1-64 of a-z 0-9 . _ -")
    ref_text = env.get("ESCALATE_REF", "")
    if ref_text and not _NUMBER.fullmatch(ref_text):
        raise EscalationError("ESCALATE_REF must be a number")
    repo = env.get("GITHUB_REPOSITORY", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    if split_repo(repo) is None or not _NUMBER.fullmatch(run_id):
        raise EscalationError("GITHUB_REPOSITORY or GITHUB_RUN_ID is missing or malformed")
    if env.get("GITHUB_SERVER_URL", "") != _SERVER:
        raise EscalationError("GITHUB_SERVER_URL is not github.com")
    return Request(
        reason=reason,
        key=key,
        ref=int(ref_text) if ref_text else None,
        run_url=f"{_SERVER}/{repo}/actions/runs/{run_id}",
    )


def _marker(key: str) -> str:
    return f"<!-- book-translator-escalation:{key} -->"


def _render(request: Request) -> tuple[str, str]:
    title, what = REASONS[request.reason]
    lines = [
        "Automation needs a human.",
        "",
        f"**What:** {what}",
        f"**Problem key:** `{request.key}`",
    ]
    if request.ref is not None:
        lines.append(f"**Related:** #{request.ref}")
    lines += [f"**Run:** {request.run_url}", "", _marker(request.key)]
    return f"{title} ({request.key})", "\n".join(lines)


def _is_ours(issue: Any, key: str) -> bool:
    if not isinstance(issue, dict) or "pull_request" in issue:
        return False
    user = issue.get("user")
    if not isinstance(user, dict) or user.get("id") != MAINT_BOT_ID or user.get("type") != "Bot":
        return False
    body = issue.get("body")
    if not isinstance(body, str):
        return False
    return _marker(key) in (line.strip() for line in body.splitlines())


def escalate(api: Api, repo: str, request: Request) -> str:
    """Open the issue, or comment on the open one for this problem. Returns what it did."""
    # No label filter: if the owner removes the label our issue must still be found, not
    # duplicated. The App's numeric ID and the marker identify it, not the label.
    for issue in api.get_pages(f"/repos/{repo}/issues?state=open"):
        if _is_ours(issue, request.key):
            number = int(issue["number"])
            base = f"/repos/{repo}/issues/{number}"
            api.post_json(
                f"{base}/comments",
                {"body": f"Still happening.\n\n**Run:** {request.run_url}"},
            )
            # Put it back in the owner's inbox if the label or the assignee was removed.
            api.post_json(f"{base}/labels", {"labels": [LABEL]})
            api.post_json(f"{base}/assignees", {"assignees": [OWNER_LOGIN]})
            return f"updated #{number}"
    title, body = _render(request)
    created = api.post_json(
        f"/repos/{repo}/issues",
        {"title": title, "body": body, "labels": [LABEL], "assignees": [OWNER_LOGIN]},
    )
    return f"created #{created['number']}"
