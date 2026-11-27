"""The `llm-review` check: an LLM may object to an agent's PR, and can never wave one through.

The reviewer's whole output is one small JSON verdict, and this module is the only reader of
it. The verdict has two values, `block` and `no-objection`: there is no "approve". Anything
else, a missing verdict included, fails the check, so an agent PR cannot merge until a
working reviewer produced `no-objection` for it. The check never posts a review on the PR.

Phase 1 status: the reviewer itself (the Anthropic call) is not built yet. The workflow gives
this check no verdict, so every Agent App PR fails here and other PRs pass untouched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from agentpr import collect
from agentpr.collect import AgentPrError, Api
from agentpr.core import is_agent_pr
from ghapi.client import ApiError, HttpApi

Decision = Literal["block", "no-objection"]
_MAX_REASONS = 20
_MAX_REASON_CHARS = 500


class ReviewError(Exception):
    """The verdict is missing, malformed or says something this check doesn't accept."""


def parse_verdict(text: str) -> tuple[Decision, list[str]]:
    """The decision and reasons from the reviewer's JSON, or ReviewError."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ReviewError("the verdict is not JSON") from None
    if not isinstance(data, dict) or not set(data) <= {"decision", "reasons"}:
        raise ReviewError("the verdict has unexpected fields")
    decision = data.get("decision")
    if decision not in ("block", "no-objection"):
        raise ReviewError("the verdict's decision is not block or no-objection")
    reasons = data.get("reasons", [])
    if (
        not isinstance(reasons, list)
        or len(reasons) > _MAX_REASONS
        or not all(isinstance(r, str) and len(r) <= _MAX_REASON_CHARS for r in reasons)
    ):
        raise ReviewError("the verdict's reasons are malformed")
    return decision, reasons


def outcome(is_agent: bool, verdict_text: str | None) -> tuple[bool, str]:
    """Whether the check passes, and one line saying why (never containing a raw newline)."""
    if not is_agent:
        return True, "not an Agent App PR: nothing to review"
    if verdict_text is None:
        return False, "no review verdict: the LLM review is not available, so this cannot pass"
    try:
        decision, reasons = parse_verdict(verdict_text)
    except ReviewError as error:
        return False, f"unusable review verdict: {error}"
    if decision == "no-objection":
        return True, "the review has no objection"
    # json.dumps escapes newlines and quotes: reviewer text can't start a workflow command.
    return False, f"the review blocks this PR: {json.dumps(reasons)}"


def run(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 pass, 1 blocked (or no verdict), 2 could not tell. Both non-zero fail the check."""
    try:
        repo = collect.require_repo(env.get("AGENTPR_REPO"), "AGENTPR_REPO")
        number = env.get("AGENTPR_PR", "")
        if not number.isdecimal() or not number.isascii():
            raise AgentPrError("AGENTPR_PR is malformed")
        if api is None:
            token = env.get("GH_TOKEN", "")
            if not token:
                raise AgentPrError("GH_TOKEN is missing")
            api = HttpApi(token)
        facts, _ = collect.pull_facts(api, repo, int(number))
        verdict_text: str | None = None
        path = env.get("AGENTPR_VERDICT_FILE")
        if path:
            try:
                with open(path, encoding="utf-8") as handle:
                    verdict_text = handle.read(100_000)
            except OSError:
                verdict_text = None
        ok, message = outcome(is_agent_pr(repo, facts), verdict_text)
    except (AgentPrError, ApiError) as error:
        print(f"llm-review: cannot decide, failing closed: {error}")
        return 2
    except Exception as error:
        print(f"llm-review: unexpected {type(error).__name__}, failing closed")
        return 2
    print(f"llm-review: {message}")
    return 0 if ok else 1
