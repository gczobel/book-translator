"""Fetch an issue for an agent, handing back only what the owner can vouch for.

Pagination that can't be completed raises ApiError (see ghapi.client); every other kind of
partial or odd data raises TrustError. Neither ever yields a half-trusted issue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from issuetrust.core import TrustError, check_not_edited_after_ready, owner_comments

_REPO = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      lastEditedAt
      userContentEdits(first: 100) {
        nodes { createdAt editor { ... on User { databaseId } } }
        pageInfo { hasNextPage }
      }
    }
  }
}
"""


class Api(Protocol):
    def get_json(self, path: str) -> Any: ...

    def get_pages(self, path: str) -> list[Any]: ...

    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class TrustedIssue:
    issue: dict[str, Any]
    comments: list[dict[str, Any]]  # the owner's only


def _edit_history(api: Api, owner: str, name: str, number: int) -> tuple[list[Any], str | None]:
    answer = api.post_json(
        "/graphql",
        {"query": _QUERY, "variables": {"owner": owner, "name": name, "number": number}},
    )
    if not isinstance(answer, dict) or answer.get("errors"):
        raise TrustError("edit history query failed")
    try:
        issue = answer["data"]["repository"]["issue"]
        edits = issue["userContentEdits"]
        nodes, more = edits["nodes"], edits["pageInfo"]["hasNextPage"]
        last = issue["lastEditedAt"]
    except (KeyError, TypeError):
        raise TrustError("edit history answer is incomplete") from None
    if more is not False:
        raise TrustError("edit history is truncated")
    if not isinstance(nodes, list) or not (last is None or isinstance(last, str)):
        raise TrustError("edit history answer is malformed")
    return nodes, last


def load_trusted_issue(api: Api, repo: str, number: int) -> TrustedIssue:
    """The issue and the owner's comments, or an exception if it can't be trusted."""
    match = _REPO.fullmatch(repo)
    if match is None:
        raise TrustError("repository is not owner/name")
    issue = api.get_json(f"/repos/{repo}/issues/{number}")
    if not isinstance(issue, dict):
        raise TrustError("issue is not an object")
    comments = api.get_pages(f"/repos/{repo}/issues/{number}/comments")
    reported = issue.get("comments")
    if isinstance(reported, bool) or not isinstance(reported, int) or len(comments) < reported:
        raise TrustError("fewer comments arrived than the issue reports")
    events = api.get_pages(f"/repos/{repo}/issues/{number}/timeline")
    edits, last_edited_at = _edit_history(api, match.group(1), match.group(2), number)
    check_not_edited_after_ready(issue, events, edits, last_edited_at)
    return TrustedIssue(issue=issue, comments=owner_comments(comments))
