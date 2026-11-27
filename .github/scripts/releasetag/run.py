"""Entry point: gather the facts about a new tag from the API and decide.

Exit 0 only for a verified release-please tag. Anything else, an unreadable answer included,
exits 1, and the escalation workflow reacts to the failed run. The tag name and the default
branch are validated before they go into an API path.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from ghapi.client import HttpApi
from ghapi.repo import split_repo
from releasetag.core import TAG, MergedPull, TagFacts, verify

_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA = re.compile(r"[0-9a-f]{40}")
_PEEL_LIMIT = 5
_ATTEMPTS = 4  # GitHub can lag a few seconds before it links a merge commit to its pull request
_WAIT_SECONDS = 5


class Api(Protocol):
    def get_json(self, path: str) -> Any: ...

    def get_pages(self, path: str) -> list[Any]: ...


class TagError(Exception):
    """The API answer is not what a real tag looks like."""


def _commit_of_tag(api: Api, repo: str, tag: str) -> str:
    ref = api.get_json(f"/repos/{repo}/git/ref/tags/{tag}")
    obj = ref.get("object") or {}
    for _ in range(_PEEL_LIMIT):
        sha = obj.get("sha")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise TagError("tag object has no valid SHA")
        if obj.get("type") == "commit":
            return sha
        if obj.get("type") != "tag":
            raise TagError("tag does not point at a commit")
        obj = (api.get_json(f"/repos/{repo}/git/tags/{sha}") or {}).get("object") or {}
    raise TagError("tag chain is too deep")


def _pull(item: Mapping[str, Any]) -> MergedPull:
    head = item.get("head") or {}
    base = item.get("base") or {}
    return MergedPull(
        number=int(item.get("number") or 0),
        author_id=(item.get("user") or {}).get("id"),
        head_repo=(head.get("repo") or {}).get("full_name"),
        base_repo=(base.get("repo") or {}).get("full_name"),
        head_ref=str(head.get("ref") or ""),
        base_ref=str(base.get("ref") or ""),
        merge_commit_sha=item.get("merge_commit_sha"),
        merged=bool(item.get("merged_at")),
        title=str(item.get("title") or ""),
    )


def gather(api: Api, repo: str, tag: str, branch: str, sleep: Callable[[float], None]) -> TagFacts:
    sha = _commit_of_tag(api, repo, tag)
    commit = api.get_json(f"/repos/{repo}/commits/{sha}")
    parents = commit.get("parents")
    if not isinstance(parents, list):
        raise TagError("commit has no parent list")
    compare = api.get_json(f"/repos/{repo}/compare/{branch}...{sha}?per_page=1")
    pulls: list[Any] = []
    for attempt in range(_ATTEMPTS):
        pulls = api.get_pages(f"/repos/{repo}/commits/{sha}/pulls")
        if pulls:
            break
        if attempt < _ATTEMPTS - 1:
            sleep(_WAIT_SECONDS)
    return TagFacts(
        tag=tag,
        commit_sha=sha,
        on_main=compare.get("status") in ("behind", "identical"),
        parent_count=len(parents),
        pulls=tuple(_pull(p) for p in pulls),
    )


def run(
    env: Mapping[str, str],
    api: Api | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    repo = env.get("GITHUB_REPOSITORY", "")
    tag = env.get("TAG_NAME", "")
    branch = env.get("DEFAULT_BRANCH", "")
    if split_repo(repo) is None or _BRANCH.fullmatch(branch) is None:
        print("releasetag: GITHUB_REPOSITORY or DEFAULT_BRANCH is missing or malformed")
        return 1
    if env.get("REF_TYPE") != "tag":
        print("releasetag: the created ref is not a tag")
        return 1
    if TAG.fullmatch(tag) is None:  # before the name reaches any API path
        print("releasetag: tag name is not vMAJOR.MINOR.PATCH")
        return 1
    try:
        if api is None:
            api = HttpApi(env.get("GH_TOKEN", ""))
        facts = gather(api, repo, tag, branch, sleep)
    except Exception as error:  # fail closed on any unreadable answer
        print(f"releasetag: cannot read the tag ({type(error).__name__}); treating as unverified")
        return 1
    verdict = verify(facts, repo, branch)
    print(f"releasetag: {'ok' if verdict.ok else 'REJECTED'}: {verdict.reason}")
    return 0 if verdict.ok else 1
