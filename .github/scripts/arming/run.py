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
from arming.core import ARMABLE_AUTHORS, Pull, evaluate, unverified_checks
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
_DISABLE = """
mutation($id: ID!) {
  disablePullRequestAutoMerge(input: {pullRequestId: $id}) {
    pullRequest { number }
  }
}
"""
# GitHub refuses to enable auto-merge on a PR that is already mergeable with this message.
CLEAN_STATUS = "clean status"
# Merging directly skips GitHub's own wait, so it happens only after every required check is
# verified successful from GitHub Actions (see `arm`); otherwise nothing is done and the next
# sweep retries.
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


def _ours(pull: Pull) -> bool:
    """An armed PR by an author this workflow arms for, so it may be disarmed."""
    return pull.armed and pull.author_id in ARMABLE_AUTHORS


def select(env: Mapping[str, str], api: Api | None = None, age_gate: AgeGate = _age_gate) -> int:
    """Publish `armable`, `disarm`, `work` and `ok` ('true' only if clean).

    `armable` lists number, head sha and the security/urgent inputs the age gate saw. PRs that
    are already armed are judged again against their current head: one that no longer qualifies,
    or fails the gate (or can't be checked), is listed in `disarm`, so a push after arming can't
    skip the age gate. Only PRs by Dependabot or the maintenance App are ever disarmed; anyone
    else's auto-merge is not this workflow's business. `work` is 'true' if either list has an
    entry (one flag, so the workflow needs no `||`).
    """
    armable: list[dict[str, Any]] = []
    disarm: list[int] = []
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
                if _ours(pull):
                    disarm.append(pull.number)
                    print(f"arming: #{pull.number} auto-merge to be disabled: {decision.reason}")
                else:
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
            if _ours(pull):  # can't verify an armed PR: fail closed
                disarm.append(pull.number)
            continue
        if verdict != 0:
            print(f"arming: #{pull.number} waits: the age gate did not pass")
            if _ours(pull):
                disarm.append(pull.number)
        elif pull.armed:
            print(f"arming: #{pull.number} is armed and still passes the age gate")
        else:
            print(f"arming: #{pull.number} passed the age gate")
            armable.append(
                {
                    "number": pull.number,
                    "head_sha": pull.head_sha,
                    "security": decision.security,
                    "urgent": decision.urgent,
                }
            )
    wrote = _publish(
        env,
        {
            "armable": json.dumps(armable),
            "disarm": json.dumps(disarm),
            "work": str(bool(armable or disarm)).lower(),
            "ok": str(ok).lower(),
        },
    )
    return 0 if wrote else 1


def _targets(text: str) -> list[tuple[int, str, bool, bool]]:
    """(number, head sha, security, urgent) as the age gate saw them."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ApiError("ARMING_TARGETS is not JSON") from error
    if not isinstance(data, list):
        raise ApiError("ARMING_TARGETS is not a list")
    result = []
    for item in data:
        item = item if isinstance(item, dict) else {}
        number, sha = item.get("number"), item.get("head_sha")
        security, urgent = item.get("security"), item.get("urgent")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not isinstance(sha, str)
            or not _SHA.fullmatch(sha)
            or not isinstance(security, bool)
            or not isinstance(urgent, bool)
        ):
            raise ApiError("ARMING_TARGETS has a malformed entry")
        result.append((number, sha, security, urgent))
    return result


def _disarm_numbers(text: str) -> list[int]:
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ApiError("ARMING_DISARM is not JSON") from error
    if not isinstance(data, list) or not all(
        isinstance(n, int) and not isinstance(n, bool) for n in data
    ):
        raise ApiError("ARMING_DISARM is not a list of numbers")
    return data


def _graphql(api: Api, query: str, variables: dict[str, str]) -> list[str]:
    """The error messages of a GraphQL call (empty on success)."""
    reply = api.post_json("/graphql", {"query": query, "variables": variables})
    errors = reply.get("errors") if isinstance(reply, dict) else ["unreadable reply"]
    if not errors:
        return []
    return [str(e.get("message", "")) if isinstance(e, dict) else str(e) for e in errors]


def arm(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 only if every selected PR was armed or merged and every disarm happened."""
    try:
        repo = _repo(env)
        targets = _targets(env.get("ARMING_TARGETS", "") or "[]")
        disarm = _disarm_numbers(env.get("ARMING_DISARM", ""))
        api = api or HttpApi(env.get("GH_TOKEN", ""))
        branch = collect.default_branch(api, repo)
    except Exception as error:
        print(f"arming: cannot start ({type(error).__name__}: {error})")
        return 1
    failed = False
    for number in disarm:
        try:
            pull = collect.one_pull(api, repo, number)
            if pull.state == "open" and pull.armed and pull.author_id in ARMABLE_AUTHORS:
                errors = _graphql(api, _DISABLE, {"id": pull.node_id})
                if errors:
                    raise ApiError("GitHub refused: " + "; ".join(errors))
                print(f"arming: #{number} auto-merge disabled")
        except Exception as error:
            print(f"arming: #{number} auto-merge NOT disabled ({type(error).__name__}: {error})")
            failed = True
    for number, sha, security, urgent in targets:
        try:
            pull = collect.one_pull(api, repo, number)
            decision = evaluate(pull, repo, branch, collect.label_events(api, repo, number))
            if not decision.arm:
                raise ApiError(f"no longer qualifies: {decision.reason}")
            if pull.head_sha != sha:
                raise ApiError("the head moved since the age gate ran")
            # The age gate ran with these inputs. A label that has since been removed (or never
            # was the right one) makes the real policy stricter: refuse rather than arm.
            if (security and not decision.security) or (urgent and not decision.urgent):
                raise ApiError("a security or urgent label the age gate relied on is gone")
            variables = {"id": pull.node_id, "oid": sha}
            errors = _graphql(api, _ENABLE, variables)
            if errors and all(CLEAN_STATUS in e for e in errors):
                # `targets` only holds PRs whose age gate passed. Merge now only if every
                # required check is verified; if any is not, do nothing and let the sweep retry.
                unverified = unverified_checks(collect.check_runs(api, repo, sha))
                if unverified:
                    print(f"arming: #{number} not merged yet: unverified checks {unverified}")
                    continue
                errors = _graphql(api, _MERGE, variables)
            if errors:
                raise ApiError("GitHub refused: " + "; ".join(errors))
            print(f"arming: #{number} armed")
        except Exception as error:
            print(f"arming: #{number} NOT armed ({type(error).__name__}: {error})")
            failed = True
    return 1 if failed else 0
