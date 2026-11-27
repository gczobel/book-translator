"""The repair workflow's script steps (ADR 0005, "Repairs").

- `select` (no write credentials): finds the PR through the API from the failed run's commit,
  decides, and publishes `action` (`repair`, `skip` or `escalate`) with structured facts.
- `build` (validate job): turns the agent's patch into a commit in a scratch object store.
- `names` (validate job): refuses dependency names the PR did not already have.
- `push` (the contents-only token): rebuilds the same commit, checks it is the validated tree,
  and records it on the PR branch through GitHub's commit API (signed, and refused if the branch
  moved).

Nothing from a PR is checked out or run, and no PR text reaches a shell or a prompt. Every
failure to decide fails closed.
"""

from __future__ import annotations

import base64
import binascii
import re
import tomllib
from collections.abc import Mapping
from typing import Any

from arming.collect import Api, parse_pull
from ghapi.client import ApiError, HttpApi
from ghapi.repo import split_repo
from repair import core, patch
from repair import names as names_mod
from repair_validate.errors import ValidateError
from repair_validate.gitdata import GitRepo

_SHA = re.compile(r"[0-9a-f]{40}")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_ATTEMPT = re.compile(r"[0-9]{1,2}")

_CREATE_COMMIT = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}
"""


def _publish(env: Mapping[str, str], lines: Mapping[str, str]) -> bool:
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return True
    try:
        with open(path, "a", encoding="utf-8") as out:
            for key, value in lines.items():
                out.write(f"{key}={value}\n")
    except OSError:
        print("repair: cannot write the step outputs")
        return False
    return True


def _sha(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not _SHA.fullmatch(value):
        raise ValidateError(f"{name} is missing or not a full commit hash")
    return value


def select(env: Mapping[str, str], api: Api | None = None) -> int:
    """Publish `action`, `reason`, `pr`, `head_sha`, `head_ref`, `attempt` and `ok`."""
    out = {
        "action": "skip",
        "reason": "",
        "pr": "",
        "head_sha": "",
        "head_ref": "",
        "attempt": "0",
        "ok": "true",
    }
    try:
        repo = env.get("GITHUB_REPOSITORY", "")
        if split_repo(repo) is None:
            raise ApiError("GITHUB_REPOSITORY is not owner/name")
        run_sha = _sha(env, "REPAIR_RUN_SHA")
        if env.get("REPAIR_RUN_EVENT") != "pull_request":
            out["reason"] = "the run was not caused by a pull request"
        else:
            client: Api = api or HttpApi(env.get("GH_TOKEN", ""))
            found = [
                pull
                for pull in map(
                    parse_pull, client.get_pages(f"/repos/{repo}/commits/{run_sha}/pulls")
                )
                if pull.state == "open" and pull.head_sha == run_sha
            ]
            if len(found) != 1:
                out["reason"] = f"{len(found)} open pull requests have this head commit"
            else:
                pull = found[0]
                commits = client.get_pages(f"/repos/{repo}/pulls/{pull.number}/commits")
                subjects = [str(c["commit"]["message"]).split("\n", 1)[0] for c in commits]
                decision = core.decide(
                    pull, repo, run_sha, env.get("REPAIR_RUN_CONCLUSION", ""), subjects
                )
                out["action"], out["reason"] = decision.action, decision.reason
                if decision.action != "skip":
                    if not _BRANCH.fullmatch(pull.head_ref):
                        raise ApiError("the head branch name is not plain")
                    out.update(
                        pr=str(pull.number),
                        head_sha=pull.head_sha,
                        head_ref=pull.head_ref,
                        attempt=str(decision.attempt),
                    )
    except Exception as error:
        print(f"repair: cannot select ({type(error).__name__}: {error})")
        out = {**out, "action": "skip", "pr": "", "head_sha": "", "head_ref": "", "ok": "false"}
    print(f"repair: {out['action']}: {out['reason']}")
    return 0 if _publish(env, out) else 1


def _decode_patch(env: Mapping[str, str]) -> str:
    try:
        raw = base64.b64decode(env.get("REPAIR_PATCH_B64", ""), validate=True)
        return raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise patch.PatchError("the patch is not base64 text") from error


def _attempt(env: Mapping[str, str]) -> int:
    value = env.get("REPAIR_ATTEMPT", "")
    if not _ATTEMPT.fullmatch(value) or not 1 <= int(value) <= core.MAX_ATTEMPTS:
        raise patch.PatchError("REPAIR_ATTEMPT is not a valid attempt number")
    return int(value)


def build(env: Mapping[str, str]) -> int:
    """Exit 0 with `head` and `tree` published; 2 if no commit can be made."""
    try:
        commit, tree = patch.build_commit(
            env.get("REPAIR_DIR") or ".",
            _sha(env, "REPAIR_BASE"),
            _decode_patch(env),
            core.commit_message(_attempt(env)),
        )
    except (patch.PatchError, ValidateError) as error:
        print(f"repair: cannot build the commit, failing closed: {error}")
        return 2
    return 0 if _publish(env, {"head": commit, "tree": tree}) else 2


def _text(tree: Any, path: str) -> str:
    return str(tree.read(path)) if path in tree.paths() else ""


def names(env: Mapping[str, str]) -> int:
    """0 if the repair adds no dependency name, 1 if it does, 2 if that can't be told."""
    try:
        repo = GitRepo(env.get("REPAIR_DIR") or ".")
        base_tree = repo.tree(_sha(env, "REPAIR_BASE"))
        head_tree = repo.tree(_sha(env, "REPAIR_HEAD"))
        added = names_mod.new_names(
            _text(base_tree, "pyproject.toml"),
            _text(head_tree, "pyproject.toml"),
            _text(base_tree, "uv.lock"),
            _text(head_tree, "uv.lock"),
        )
    except (ValidateError, tomllib.TOMLDecodeError) as error:
        print(f"repair-names: cannot decide, failing closed: {error}")
        return 2
    except Exception as error:
        print(f"repair-names: unexpected {type(error).__name__}, failing closed")
        return 2
    for name in added:
        print(f"  rejected: new dependency name {name!r}")
    if added:
        print(f"repair-names: REJECTED, {len(added)} new name(s)")
        return 1
    print("repair-names: passed")
    return 0


def push(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 only if the validated patch is now a commit on the PR branch."""
    try:
        repo = env.get("GITHUB_REPOSITORY", "")
        if split_repo(repo) is None:
            raise ApiError("GITHUB_REPOSITORY is not owner/name")
        branch = env.get("REPAIR_BRANCH", "")
        if not _BRANCH.fullmatch(branch):
            raise ApiError("REPAIR_BRANCH is not a plain branch name")
        directory = env.get("REPAIR_DIR") or "."
        base = _sha(env, "REPAIR_BASE")
        message = core.commit_message(_attempt(env))
        commit, tree = patch.build_commit(directory, base, _decode_patch(env), message)
        if tree != _sha(env, "REPAIR_TREE"):
            raise ApiError("the patch does not give the tree the validator judged")
        changes = patch.file_changes(directory, base, commit)
        client: Api = api or HttpApi(env.get("GH_TOKEN", ""))
        reply = client.post_json(
            "/graphql",
            {
                "query": _CREATE_COMMIT,
                "variables": {
                    "input": {
                        "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
                        "message": {"headline": message},
                        "expectedHeadOid": base,
                        "fileChanges": {
                            "additions": [
                                {"path": p, "contents": base64.b64encode(c).decode()}
                                for p, c in sorted(changes.additions.items())
                            ],
                            "deletions": [{"path": p} for p in sorted(changes.deletions)],
                        },
                    }
                },
            },
        )
        errors = reply.get("errors") if isinstance(reply, dict) else ["unreadable reply"]
        if errors:
            raise ApiError(f"GitHub refused: {errors}")
    except Exception as error:
        print(f"repair-push: NOT pushed ({type(error).__name__}: {error})")
        return 1
    print("repair-push: pushed")
    return 0
