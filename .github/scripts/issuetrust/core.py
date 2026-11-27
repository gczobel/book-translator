"""Who an agent may believe: the owner's comments, and issues unchanged since they were readied.

Identity is the numeric GitHub user ID, never the login: a login can be renamed, reused or
imitated, an ID cannot. Anything missing, mistyped or unexplained raises TrustError, so the
caller refuses instead of guessing (ADR 0005, invariants 2 and 6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

OWNER_ID = 754466
READY_LABEL = "ready-for-agent"


class TrustError(Exception):
    """The data is incomplete, malformed or untrusted, so the agent must not act on it."""


def _obj(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrustError(f"{what} is not an object")
    return value


def _user_id(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrustError(f"{what} id is not an integer")
    return value


def _time(value: Any, what: str) -> datetime:
    if not isinstance(value, str):
        raise TrustError(f"{what} has no time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise TrustError(f"{what} has an unreadable time") from None
    if parsed.tzinfo is None:
        raise TrustError(f"{what} time has no timezone")
    return parsed


def owner_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The comments written by the owner. A comment whose author is gone is not the owner's."""
    kept = []
    for raw in comments:
        comment = _obj(raw, "comment")
        user = comment.get("user")
        if user is None:
            continue
        if _user_id(_obj(user, "comment author").get("id"), "comment author") == OWNER_ID:
            kept.append(comment)
    return kept


def _actor_id(event: dict[str, Any]) -> int:
    return _user_id(_obj(event.get("actor"), "event actor").get("id"), "event actor")


def _ready_time(events: list[dict[str, Any]]) -> datetime:
    """When ready-for-agent was last applied by the owner and not removed since."""
    current: datetime | None = None
    for raw in events:
        event = _obj(raw, "timeline event")
        kind = event.get("event")
        if kind not in ("labeled", "unlabeled"):
            continue
        label = event.get("label")
        if _obj(label, "event label").get("name") != READY_LABEL:
            continue
        at = _time(event.get("created_at"), f"{kind} event")
        if kind == "unlabeled":
            current = None
        elif _actor_id(event) != OWNER_ID:
            raise TrustError(f"{READY_LABEL} was not applied by the owner")
        elif current is None or at > current:
            current = at
    if current is None:
        raise TrustError(f"{READY_LABEL} is not applied")
    return current


def check_not_edited_after_ready(
    issue: dict[str, Any],
    events: list[dict[str, Any]],
    edits: list[dict[str, Any]],
    last_edited_at: str | None,
) -> None:
    """Raise TrustError unless the issue is the owner's and nobody else changed it since ready.

    `events` is the issue timeline (label and rename events, with actors); `edits` is the
    body edit history (GraphQL userContentEdits: createdAt and editor.databaseId);
    `last_edited_at` is the issue's own lastEditedAt, used to catch history that is missing.
    """
    author = _obj(_obj(issue, "issue").get("user"), "issue author")
    if _user_id(author.get("id"), "issue author") != OWNER_ID:
        raise TrustError("issue author is not the owner")
    ready = _ready_time(events)
    explained: list[datetime] = []

    for raw in edits:
        edit = _obj(raw, "edit")
        at = _time(edit.get("createdAt"), "edit")
        explained.append(at)
        if at < ready:
            continue
        editor = edit.get("editor")
        if (
            editor is None
            or _user_id(_obj(editor, "editor").get("databaseId"), "editor") != OWNER_ID
        ):
            raise TrustError(f"issue was edited after {READY_LABEL} by someone but the owner")

    for raw in events:
        event = _obj(raw, "timeline event")
        if event.get("event") != "renamed":
            continue
        at = _time(event.get("created_at"), "renamed event")
        explained.append(at)
        if at >= ready and _actor_id(event) != OWNER_ID:
            raise TrustError(f"issue was renamed after {READY_LABEL} by someone but the owner")

    if last_edited_at is not None:
        last = _time(last_edited_at, "lastEditedAt")
        if last >= ready and not any(at >= last for at in explained):
            raise TrustError("edit history does not explain the last edit")
