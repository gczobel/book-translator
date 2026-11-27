"""Turn GitHub's JSON into the plain data `core` decides on, refusing anything malformed."""

from __future__ import annotations

import re
from typing import Any, Protocol

from arming.core import LabelEvent, Pull
from ghapi.client import ApiError

_SHA = re.compile(r"[0-9a-f]{40}")


class Api(Protocol):
    def get_json(self, path: str) -> Any: ...

    def get_pages(self, path: str) -> list[Any]: ...

    def get_text(self, path: str) -> str | None: ...

    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


def _obj(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError(f"{what} is not an object")
    return value


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ApiError(f"{what} is not a string")
    return value


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"{what} is not an integer")
    return value


def parse_pull(raw: Any) -> Pull:
    item = _obj(raw, "pull request")
    number = _int(item.get("number"), "number")
    author_id = _int(_obj(item.get("user"), "author").get("id"), "author id")
    head, base = _obj(item.get("head"), "head"), _obj(item.get("base"), "base")
    head_repo = head.get("repo")  # null once a fork is deleted
    sha = _str(head.get("sha"), "head sha")
    if not _SHA.fullmatch(sha):
        raise ApiError("head sha is not a commit hash")
    labels = item.get("labels")
    if not isinstance(labels, list):
        raise ApiError("labels is not a list")
    return Pull(
        number=number,
        node_id=_str(item.get("node_id"), "node id"),
        state=_str(item.get("state"), "state"),
        author_id=author_id,
        head_repo=_str(_obj(head_repo, "head repo").get("full_name"), "head repo name")
        if head_repo is not None
        else None,
        base_repo=_str(_obj(base.get("repo"), "base repo").get("full_name"), "base repo name"),
        head_ref=_str(head.get("ref"), "head ref"),
        base_ref=_str(base.get("ref"), "base ref"),
        head_sha=sha,
        labels=frozenset(_str(_obj(x, "label").get("name"), "label name").lower() for x in labels),
        armed=item.get("auto_merge") is not None,
    )


def default_branch(api: Api, repo: str) -> str:
    return _str(_obj(api.get_json(f"/repos/{repo}"), "repository").get("default_branch"), "branch")


def open_pulls(api: Api, repo: str) -> list[Pull]:
    return [parse_pull(raw) for raw in api.get_pages(f"/repos/{repo}/pulls?state=open")]


def one_pull(api: Api, repo: str, number: int) -> Pull:
    return parse_pull(api.get_json(f"/repos/{repo}/pulls/{number}"))


def label_events(api: Api, repo: str, number: int) -> list[LabelEvent]:
    """Label add/remove events in order. Other event kinds are skipped; odd ones fail closed."""
    events: list[LabelEvent] = []
    for raw in api.get_pages(f"/repos/{repo}/issues/{number}/events"):
        item = _obj(raw, "event")
        action = item.get("event")
        if action not in ("labeled", "unlabeled"):
            continue
        actor = item.get("actor")
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        events.append(
            LabelEvent(
                label=_str(_obj(item.get("label"), "event label").get("name"), "label name"),
                action=action,
                actor_id=actor_id if isinstance(actor_id, int) else None,
            )
        )
    return events
