"""The `llm-review` check: it may block, it never approves, and it fails closed."""

import json
from pathlib import Path
from typing import Any

import pytest

from agentpr.review import ReviewError, outcome, parse_verdict, run
from ghapi.identities import AGENT_BOT_ID, OWNER_ID

REPO = "o/r"


def test_no_objection_passes_an_agent_pr() -> None:
    ok, _ = outcome(is_agent=True, verdict_text=json.dumps({"decision": "no-objection"}))
    assert ok


def test_a_block_fails_and_keeps_its_reasons_as_escaped_data() -> None:
    text = json.dumps({"decision": "block", "reasons": ["::error::x\nbad"]})
    ok, message = outcome(is_agent=True, verdict_text=text)
    assert not ok
    assert "\n" not in message
    assert not message.startswith("::")


def test_no_verdict_fails_an_agent_pr_until_the_review_is_built() -> None:
    ok, message = outcome(is_agent=True, verdict_text=None)
    assert not ok
    assert "no review verdict" in message


def test_other_prs_are_not_reviewed_and_pass() -> None:
    assert outcome(is_agent=False, verdict_text=None)[0]
    assert outcome(is_agent=False, verdict_text="garbage")[0]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "null",
        '{"decision": "approve"}',
        '{"decision": "APPROVED"}',
        '{"decision": "pass"}',
        '{"decision": true}',
        '{"decision": "block", "reasons": "x"}',
        '{"decision": "block", "reasons": [1]}',
        '{"decision": "no-objection", "approve": true}',
        '{"decision": "no-objection"} trailing',
        '{"decision": "no-objection", "reasons": ["' + "x" * 600 + '"]}',
        '{"decision": "no-objection", "reasons": [' + ",".join(['"a"'] * 30) + "]}",
    ],
)
def test_anything_but_a_strict_verdict_is_an_error(text: str) -> None:
    with pytest.raises(ReviewError):
        parse_verdict(text)
    assert not outcome(is_agent=True, verdict_text=text)[0]


class FakeApi:
    def __init__(self, author_id: int) -> None:
        self.author_id = author_id

    def get_json(self, path: str) -> Any:
        assert path == f"/repos/{REPO}/pulls/7"
        return {
            "number": 7,
            "state": "open",
            "merged": False,
            "draft": False,
            "user": {"id": self.author_id, "type": "Bot"},
            "head": {"sha": "1" * 40, "ref": "agent/x", "repo": {"full_name": REPO}},
            "base": {"ref": "main", "repo": {"full_name": REPO, "default_branch": "main"}},
            "labels": [],
            "changed_files": 0,
        }

    def get_pages(self, path: str) -> list[Any]:
        return []


ENV = {"AGENTPR_REPO": REPO, "AGENTPR_PR": "7"}


def test_the_placeholder_blocks_an_agent_pr_and_passes_the_owners() -> None:
    assert run(ENV, FakeApi(AGENT_BOT_ID)) == 1
    assert run(ENV, FakeApi(OWNER_ID)) == 0


def test_a_verdict_file_decides(tmp_path: Path) -> None:
    path = tmp_path / "verdict.json"
    path.write_text('{"decision": "no-objection"}')
    env = {**ENV, "AGENTPR_VERDICT_FILE": str(path)}
    assert run(env, FakeApi(AGENT_BOT_ID)) == 0
    path.write_text('{"decision": "block", "reasons": ["a"]}')
    assert run(env, FakeApi(AGENT_BOT_ID)) == 1
    assert (
        run({**env, "AGENTPR_VERDICT_FILE": str(tmp_path / "missing")}, FakeApi(AGENT_BOT_ID)) == 1
    )


def test_an_unreadable_pr_fails_closed() -> None:
    assert run({"AGENTPR_REPO": REPO, "AGENTPR_PR": "x"}, FakeApi(AGENT_BOT_ID)) == 2
    assert run({"AGENTPR_REPO": "bad", "AGENTPR_PR": "7"}, FakeApi(AGENT_BOT_ID)) == 2

    class Broken(FakeApi):
        def get_json(self, path: str) -> Any:
            raise TimeoutError

    assert run(ENV, Broken(AGENT_BOT_ID)) == 2


def test_the_module_never_posts_a_review() -> None:
    source = (
        Path(__file__).resolve().parent.parent / ".github/scripts/agentpr/review.py"
    ).read_text()
    for forbidden in ("post_json", "/reviews", "APPROVE", "approve("):
        assert forbidden not in source
