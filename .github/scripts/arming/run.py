"""The two steps of the arming workflow.

`select` runs without write credentials: it lists open PRs, decides which qualify, fetches each
head `uv.lock` as data, runs the age gate, and publishes the survivors. `arm` runs with the
maintenance App's token: it re-checks each survivor against the live PR and enables squash
auto-merge with a blank commit body, pinned to the head commit that was checked.

Nothing from a PR is checked out or executed. Every failure leaves a PR unarmed (fail closed);
`select` also publishes `ok=false` and `arm` exits non-zero, which the workflow escalates.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from arming import collect
from arming.collect import Api
from arming.core import Pull, evaluate
from ghapi.client import ApiError, HttpApi
from ghapi.repo import split_repo

AgeGate = Callable[[Mapping[str, str]], int]

_SHA = re.compile(r"[0-9a-f]{40}")

_ENABLE = """
mutation($id: ID!, $oid: GitObjectID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH, commitBody: "",
                                     expectedHeadOid: $oid}) {
    pullRequest { number }
  }
}
"""
# An already-green PR can't have auto-merge enabled ("clean status"); merge it directly instead.
_MERGE = """
mutation($id: ID!, $oid: GitObjectID!) {
  mergePullRequest(input: {pullRequestId: $id, mergeMethod: SQUASH, commitBody: "",
                           expectedHeadOid: $oid}) {
    pullRequest { number }
  }
}
"""


def _age_gate(env: Mapping[str, str]) -> int:
    from lockage.run import run as lockage_run

    return lockage_run(env)


def _repo(env: Mapping[str, str]) -> str:
    repo = env.get("GITHUB_REPOSITORY", "")
    if split_repo(repo) is None:
        raise ApiError("GITHUB_REPOSITORY is not owner/name")
    return repo


def _publish(env: Mapping[str, str], lines: dict[str, str]) -> bool:
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return True
    try:
        with open(path, "a", encoding="utf-8") as out:
            for key, value in lines.items():
                out.write(f"{key}={value}\n")
    except OSError:
        print("arming: cannot write the step outputs")
        return False
    return True


def select(env: Mapping[str, str], api: Api | None = None, age_gate: AgeGate = _age_gate) -> int:
    """Publish `armable` (JSON list of number and head sha) and `ok` ('true' only if clean)."""
    armable: list[dict[str, Any]] = []
    ok = True
    pulls: list[Pull] = []
    try:
        repo = _repo(env)
        client: Api = api or HttpApi(env.get("GH_TOKEN", ""))
        branch = collect.default_branch(client, repo)
        pulls = collect.open_pulls(client, repo)
    except Exception as error:
        print(f"arming: cannot list pull requests ({type(error).__name__}: {error})")
        ok = False
    for pull in pulls:
        try:
            events = collect.label_events(client, repo, pull.number)
            decision = evaluate(pull, repo, branch, events)
            if not decision.arm:
                print(f"arming: #{pull.number} skipped: {decision.reason}")
                continue
            head_lock = client.get_text(f"/repos/{repo}/contents/uv.lock?ref={pull.head_sha}")
            if head_lock is None:
                raise ApiError("the head has no uv.lock")
            target = Path(env["ARMING_WORKDIR"]) / f"head-{pull.number}.lock"
            target.write_text(head_lock, encoding="utf-8")
            verdict = age_gate(
                {  # only what the gate reads; no GITHUB_OUTPUT, so it can't write ours
                    "BASE_LOCK": env["ARMING_BASE_LOCK"],
                    "HEAD_LOCK": str(target),
                    "IS_SECURITY": str(decision.security).lower(),
                    "URGENT": str(decision.urgent).lower(),
                }
            )
        except Exception as error:
            print(f"arming: #{pull.number} not armed ({type(error).__name__}: {error})")
            ok = False
            continue
        if verdict == 0:
            print(f"arming: #{pull.number} passed the age gate")
            armable.append({"number": pull.number, "head_sha": pull.head_sha})
        else:
            print(f"arming: #{pull.number} waits: the age gate did not pass")
    wrote = _publish(env, {"armable": json.dumps(armable), "ok": str(ok).lower()})
    return 0 if wrote else 1


def _targets(text: str) -> list[tuple[int, str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ApiError("ARMING_TARGETS is not JSON") from error
    if not isinstance(data, list):
        raise ApiError("ARMING_TARGETS is not a list")
    result = []
    for item in data:
        number = item.get("number") if isinstance(item, dict) else None
        sha = item.get("head_sha") if isinstance(item, dict) else None
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not isinstance(sha, str)
            or not _SHA.fullmatch(sha)
        ):
            raise ApiError("ARMING_TARGETS has a malformed entry")
        result.append((number, sha))
    return result


def _graphql(api: Api, query: str, variables: dict[str, str]) -> list[str]:
    """The error messages of a GraphQL call (empty on success)."""
    reply = api.post_json("/graphql", {"query": query, "variables": variables})
    errors = reply.get("errors") if isinstance(reply, dict) else ["unreadable reply"]
    if not errors:
        return []
    return [str(e.get("message", "")) if isinstance(e, dict) else str(e) for e in errors]


def arm(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 only if every selected PR was armed or merged."""
    try:
        repo = _repo(env)
        targets = _targets(env.get("ARMING_TARGETS", ""))
        api = api or HttpApi(env.get("GH_TOKEN", ""))
        branch = collect.default_branch(api, repo)
    except Exception as error:
        print(f"arming: cannot start ({type(error).__name__}: {error})")
        return 1
    failed = False
    for number, sha in targets:
        try:
            pull = collect.one_pull(api, repo, number)
            decision = evaluate(pull, repo, branch, collect.label_events(api, repo, number))
            if not decision.arm:
                raise ApiError(f"no longer qualifies: {decision.reason}")
            if pull.head_sha != sha:
                raise ApiError("the head moved since the age gate ran")
            variables = {"id": pull.node_id, "oid": sha}
            errors = _graphql(api, _ENABLE, variables)
            if errors and all("clean status" in e for e in errors):
                errors = _graphql(api, _MERGE, variables)
            if errors:
                raise ApiError("GitHub refused: " + "; ".join(errors))
            print(f"arming: #{number} armed")
        except Exception as error:
            print(f"arming: #{number} NOT armed ({type(error).__name__}: {error})")
            failed = True
    return 1 if failed else 0
