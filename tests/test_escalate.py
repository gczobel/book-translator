"""The escalation job: one ready-for-human issue per problem, never hijackable."""

from typing import Any

import pytest

from escalate import core
from escalate.core import EscalationError, Request, escalate, parse_request
from escalate.run import run

REPO = "o/r"
BOT = core.MAINT_BOT_ID
MARKER = "<!-- book-translator-escalation:{key} -->"


class FakeApi:
    def __init__(self, open_issues: list[dict[str, Any]] | None = None) -> None:
        self.open_issues = open_issues or []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def get_pages(self, path: str) -> list[Any]:
        assert path == f"/repos/{REPO}/issues?state=open&labels=ready-for-human"
        return self.open_issues

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        self.posts.append((path, payload))
        return {"number": 99}


def _request(**over: Any) -> Request:
    base: dict[str, Any] = {
        "reason": "workflow-failed",
        "key": "repair-pr-12",
        "ref": 12,
        "run_url": "https://github.com/o/r/actions/runs/555",
    }
    base.update(over)
    return Request(**base)


def _issue(
    number: int = 5, *, body: str, user_id: int = BOT, kind: str = "Bot", **extra: Any
) -> dict[str, Any]:
    return {
        "number": number,
        "body": body,
        "user": {"id": user_id, "type": kind},
        **extra,
    }


# --- creating and updating ------------------------------------------------------------------


def test_a_new_problem_opens_one_issue_for_the_owner() -> None:
    api = FakeApi()
    assert escalate(api, REPO, _request()) == "created #99"
    ((path, payload),) = api.posts
    assert path == f"/repos/{REPO}/issues"
    assert payload["labels"] == ["ready-for-human"]
    assert payload["assignees"] == [core.OWNER_LOGIN]
    assert "repair-pr-12" in payload["title"]
    assert MARKER.format(key="repair-pr-12") in payload["body"].splitlines()
    assert "#12" in payload["body"]
    assert "https://github.com/o/r/actions/runs/555" in payload["body"]


def test_the_same_problem_again_comments_instead_of_opening_a_second_issue() -> None:
    existing = _issue(7, body="x\n" + MARKER.format(key="repair-pr-12"))
    api = FakeApi([existing])
    assert escalate(api, REPO, _request()) == "updated #7"
    ((path, payload),) = api.posts
    assert path == f"/repos/{REPO}/issues/7/comments"
    assert "https://github.com/o/r/actions/runs/555" in payload["body"]


def test_a_different_problem_gets_its_own_issue() -> None:
    other = _issue(7, body=MARKER.format(key="repair-pr-99"))
    api = FakeApi([other])
    assert escalate(api, REPO, _request()) == "created #99"


# --- never touch anyone else's issue ----------------------------------------------------------


def test_a_look_alike_issue_by_someone_else_is_ignored() -> None:
    fake = _issue(7, body=MARKER.format(key="repair-pr-12"), user_id=123, kind="User")
    api = FakeApi([fake])
    assert escalate(api, REPO, _request()) == "created #99"
    assert all("/issues/7" not in path for path, _ in api.posts)


def test_another_bot_with_the_marker_is_ignored() -> None:
    fake = _issue(7, body=MARKER.format(key="repair-pr-12"), user_id=BOT + 1)
    assert escalate(FakeApi([fake]), REPO, _request()) == "created #99"


def test_our_bots_issue_without_the_marker_is_ignored() -> None:
    plain = _issue(7, body="a note, no marker")
    assert escalate(FakeApi([plain]), REPO, _request()) == "created #99"


def test_a_pull_request_is_never_an_escalation() -> None:
    pr = _issue(7, body=MARKER.format(key="repair-pr-12"), pull_request={"url": "x"})
    assert escalate(FakeApi([pr]), REPO, _request()) == "created #99"


def test_the_marker_must_be_a_whole_line_not_quoted_text() -> None:
    quoted = _issue(7, body="see " + MARKER.format(key="repair-pr-12") + " for details")
    assert escalate(FakeApi([quoted]), REPO, _request()) == "created #99"


def test_an_issue_with_no_body_or_user_is_skipped() -> None:
    odd: list[dict[str, Any]] = [
        {"number": 1, "body": None, "user": {"id": BOT, "type": "Bot"}},
        {"number": 2},
    ]
    assert escalate(FakeApi(odd), REPO, _request()) == "created #99"


# --- structured inputs only -------------------------------------------------------------------

ENV = {
    "ESCALATE_REASON": "workflow-failed",
    "ESCALATE_KEY": "repair-pr-12",
    "ESCALATE_REF": "12",
    "GITHUB_REPOSITORY": REPO,
    "GITHUB_RUN_ID": "555",
    "GITHUB_SERVER_URL": "https://github.com",
}


def test_parse_builds_the_request_and_the_run_url() -> None:
    assert parse_request(ENV) == _request()


def test_the_reference_is_optional() -> None:
    env = {k: v for k, v in ENV.items() if k != "ESCALATE_REF"}
    assert parse_request(env).ref is None
    assert parse_request({**ENV, "ESCALATE_REF": ""}).ref is None


@pytest.mark.parametrize(
    "override",
    [
        {"ESCALATE_REASON": "free text from a PR title"},
        {"ESCALATE_REASON": ""},
        {"ESCALATE_KEY": "has spaces"},
        {"ESCALATE_KEY": "UPPER"},
        {"ESCALATE_KEY": "x" * 65},
        {"ESCALATE_KEY": "a-->\n<!-- fake"},
        {"ESCALATE_KEY": ""},
        {"ESCALATE_REF": "12; drop"},
        {"ESCALATE_REF": "-1"},
        {"GITHUB_REPOSITORY": "no-slash"},
        {"GITHUB_RUN_ID": "abc"},
        {"GITHUB_SERVER_URL": "https://evil.example"},
    ],
)
def test_anything_unstructured_is_refused(override: dict[str, str]) -> None:
    with pytest.raises(EscalationError):
        parse_request({**ENV, **override})


def test_missing_variables_are_refused() -> None:
    for name in ENV:
        if name == "ESCALATE_REF":
            continue
        with pytest.raises(EscalationError):
            parse_request({k: v for k, v in ENV.items() if k != name})


# --- the entry point --------------------------------------------------------------------------


def test_run_returns_zero_after_creating_the_issue(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ENV, FakeApi()) == 0
    assert "created #99" in capsys.readouterr().out


def test_run_fails_loudly_on_bad_input_without_calling_github() -> None:
    api = FakeApi()
    assert run({**ENV, "ESCALATE_KEY": "bad key"}, api) != 0
    assert not api.posts


def test_run_fails_loudly_when_github_fails() -> None:
    class Broken(FakeApi):
        def get_pages(self, path: str) -> list[Any]:
            raise OSError("down")

    assert run(ENV, Broken()) != 0


def test_run_needs_a_token_when_no_client_is_given() -> None:
    assert run(ENV) != 0
