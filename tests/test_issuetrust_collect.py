"""Loading an issue for an agent: owner comments only, refusing anything edited or incomplete."""

from typing import Any

import pytest

from ghapi.client import ApiError
from issuetrust.collect import load_trusted_issue
from issuetrust.core import OWNER_ID, TrustError

REPO = "o/r"
T0 = "2026-11-01T10:00:00Z"
T1 = "2026-11-02T10:00:00Z"
STRANGER = 99
LOOKALIKE = 7544660


class FakeApi:
    def __init__(
        self,
        *,
        issue_author: int = OWNER_ID,
        comments: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        graphql: dict[str, Any] | None = None,
    ) -> None:
        self.comments = comments if comments is not None else []
        self.issue = {
            "number": 7,
            "title": "t",
            "body": "b",
            "user": {"login": "gczobel", "id": issue_author},
            "comments": len(self.comments),
        }
        self.events = (
            events
            if events is not None
            else [
                {
                    "event": "labeled",
                    "created_at": T0,
                    "actor": {"id": OWNER_ID},
                    "label": {"name": "ready-for-agent"},
                }
            ]
        )
        self.graphql = graphql if graphql is not None else _graphql([], None)
        self.queries: list[dict[str, Any]] = []

    def get_json(self, path: str) -> Any:
        assert path == f"/repos/{REPO}/issues/7"
        return self.issue

    def get_pages(self, path: str) -> list[Any]:
        if path == f"/repos/{REPO}/issues/7/comments":
            return self.comments
        assert path == f"/repos/{REPO}/issues/7/timeline"
        return self.events

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        assert path == "/graphql"
        self.queries.append(payload)
        return self.graphql


def _graphql(
    edits: list[dict[str, Any]], last_edited_at: str | None, more: bool = False
) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "issue": {
                    "lastEditedAt": last_edited_at,
                    "userContentEdits": {"nodes": edits, "pageInfo": {"hasNextPage": more}},
                }
            }
        }
    }


def _comment(user_id: int, login: str, body: str) -> dict[str, Any]:
    return {"id": 1, "body": body, "user": {"login": login, "id": user_id}}


def test_returns_the_issue_with_only_the_owners_comments() -> None:
    api = FakeApi(
        comments=[
            _comment(OWNER_ID, "gczobel", "mine"),
            _comment(LOOKALIKE, "gczobel", "same login, other id"),
            _comment(STRANGER, "gczobel_", "imitator"),
        ]
    )
    trusted = load_trusted_issue(api, REPO, 7)
    assert [c["body"] for c in trusted.comments] == ["mine"]
    assert trusted.issue["number"] == 7


def test_the_graphql_query_names_the_repository_and_issue() -> None:
    api = FakeApi()
    load_trusted_issue(api, REPO, 7)
    variables = api.queries[0]["variables"]
    assert variables == {"owner": "o", "name": "r", "number": 7}


def test_refuses_an_issue_edited_by_a_stranger_after_ready() -> None:
    edit = {"createdAt": T1, "editor": {"databaseId": STRANGER}}
    api = FakeApi(graphql=_graphql([edit], T1))
    with pytest.raises(TrustError, match="edited"):
        load_trusted_issue(api, REPO, 7)


def test_accepts_an_issue_edited_by_the_owner_after_ready() -> None:
    edit = {"createdAt": T1, "editor": {"databaseId": OWNER_ID}}
    load_trusted_issue(FakeApi(graphql=_graphql([edit], T1)), REPO, 7)


def test_refuses_truncated_edit_history() -> None:
    api = FakeApi(graphql=_graphql([], None, more=True))
    with pytest.raises(TrustError, match="truncated"):
        load_trusted_issue(api, REPO, 7)


def test_refuses_when_fewer_comments_arrive_than_the_issue_reports() -> None:
    api = FakeApi(comments=[_comment(OWNER_ID, "gczobel", "x")])
    api.issue["comments"] = 2
    with pytest.raises(TrustError, match="comments"):
        load_trusted_issue(api, REPO, 7)


@pytest.mark.parametrize(
    "bad",
    [{}, {"errors": [{"message": "boom"}]}, {"data": None}, {"data": {"repository": None}}],
)
def test_refuses_a_graphql_answer_that_is_an_error_or_incomplete(bad: dict[str, Any]) -> None:
    with pytest.raises(TrustError):
        load_trusted_issue(FakeApi(graphql=bad), REPO, 7)


def test_refuses_a_bad_repository_name() -> None:
    with pytest.raises(TrustError):
        load_trusted_issue(FakeApi(), "not a repo", 7)


def test_a_failed_listing_propagates_as_an_api_error() -> None:
    class Broken(FakeApi):
        def get_pages(self, path: str) -> list[Any]:
            raise ApiError("too many pages to read them all")

    with pytest.raises(ApiError):
        load_trusted_issue(Broken(), REPO, 7)
