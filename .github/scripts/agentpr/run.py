"""Entry point of the merge job: decide which Agent PR (if any) may merge, publish the answer.

Outputs `merge` ('true' only for exactly one PR), `pr` and `sha`. The workflow merges with
`gh pr merge --rebase --match-head-commit <sha>`, so a push after this decision is refused.
Not merging is a normal outcome (exit 0); a failure to decide is exit 2 and escalates.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from agentpr import collect
from agentpr.collect import AgentPrError, Api
from agentpr.core import decide, is_agent_pr
from ghapi.client import ApiError, HttpApi


def _numbers(api: Api, repo: str, env: Mapping[str, str]) -> list[int]:
    sha, pr = env.get("AGENTPR_SHA", ""), env.get("AGENTPR_PR", "")
    if bool(sha) == bool(pr):
        raise AgentPrError("exactly one of AGENTPR_SHA and AGENTPR_PR is required")
    if pr:
        if not re.fullmatch(r"[0-9]{1,9}", pr):
            raise AgentPrError("AGENTPR_PR is malformed")
        return [int(pr)]
    return collect.candidates(api, repo, sha)


def _write_outputs(path: str, merge: bool, pr: int | None, sha: str | None) -> None:
    lines = [f"merge={str(merge).lower()}"]
    if merge:
        lines += [f"pr={pr}", f"sha={sha}"]
    with open(path, "a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def run(env: Mapping[str, str], api: Api | None = None) -> int:
    try:
        repo = collect.require_repo(env.get("AGENTPR_REPO"), "AGENTPR_REPO")
        output = env.get("GITHUB_OUTPUT")
        if not output:
            raise AgentPrError("GITHUB_OUTPUT is not set")
        if api is None:
            token = env.get("GH_TOKEN", "")
            if not token:
                raise AgentPrError("GH_TOKEN is missing")
            api = HttpApi(token)

        tags = collect.tag_names(api, repo)
        ready: list[tuple[int, str]] = []
        for number in _numbers(api, repo, env):
            facts, expected = collect.pull_facts(api, repo, number)
            if not is_agent_pr(repo, facts):
                print(f"agentpr: #{number} is not an Agent App PR from this repository; skipped")
                continue
            decision = decide(
                repo,
                facts,
                collect.changed_paths(api, repo, number, expected),
                collect.check_runs(api, repo, facts.head_sha),
                tags,
            )
            if decision.merge:
                ready.append((number, facts.head_sha))
                continue
            for reason in decision.reasons:
                print(f"agentpr: #{number} not merging: {reason}")
        if len(ready) > 1:
            raise AgentPrError("more than one PR is ready for one commit; refusing to pick")
        if ready:
            number, sha = ready[0]
            print(f"agentpr: #{number} may merge")
            _write_outputs(output, True, number, sha)
        else:
            _write_outputs(output, False, None, None)
    except (AgentPrError, ApiError) as error:
        print(f"agentpr: cannot decide, failing closed: {error}")
        return 2
    except Exception as error:  # anything unexpected must still fail the job
        print(f"agentpr: unexpected {type(error).__name__}, failing closed")
        return 2
    return 0
