"""Owner-only filtering and the edited-after-ready check, on recorded API payload shapes."""

from typing import Any

import pytest

from issuetrust.core import (
    OWNER_ID,
    TrustError,
    check_not_edited_after_ready,
    owner_comments,
)

LOOKALIKE_ID = 7544660  # a different account, one digit away
T0 = "2026-11-01T10:00:00Z"
T1 = "2026-11-02T10:00:00Z"
T2 = "2026-11-03T10:00:00Z"


def _comment(user_id: Any, login: str = "gczobel", body: str = "hi") -> dict[str, Any]:
    return {"id": 1, "body": body, "user": {"login": login, "id": user_id}}


def test_keeps_only_comments_by_the_owner_id() -> None:
    comments = [
        _comment(OWNER_ID, body="mine"),
        _comment(LOOKALIKE_ID, login="gczobel", body="same login, other id"),
        _comment(1234, login="gczobel-owner", body="owner-ish name"),
        _comment(OWNER_ID, login="renamed", body="mine after a rename"),
    ]
    assert [c["body"] for c in owner_comments(comments)] == ["mine", "mine after a rename"]


def test_a_comment_from_a_deleted_account_is_dropped() -> None:
    assert owner_comments([{"id": 1, "body": "x", "user": None}]) == []


@pytest.mark.parametrize("bad", ["754466", 754466.0, True, None])
def test_a_non_integer_id_is_an_error_not_a_match(bad: Any) -> None:
    with pytest.raises(TrustError):
        owner_comments([_comment(bad)])


def test_a_malformed_comment_is_an_error() -> None:
    with pytest.raises(TrustError):
        owner_comments(["nope"])  # type: ignore[list-item]


def _issue(author: int = OWNER_ID) -> dict[str, Any]:
    return {"user": {"login": "gczobel", "id": author}}


def _labeled(at: str, actor: int = OWNER_ID, name: str = "ready-for-agent") -> dict[str, Any]:
    return {"event": "labeled", "created_at": at, "actor": {"id": actor}, "label": {"name": name}}


def _edit(at: str, editor: int | None) -> dict[str, Any]:
    return {"createdAt": at, "editor": None if editor is None else {"databaseId": editor}}


def _check(
    issue: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    edits: list[dict[str, Any]] | None = None,
    last_edited_at: str | None = None,
) -> None:
    check_not_edited_after_ready(
        issue or _issue(),
        [_labeled(T0)] if events is None else events,
        edits or [],
        last_edited_at,
    )


def test_an_unedited_issue_passes() -> None:
    _check()


def test_an_edit_before_the_label_is_fine() -> None:
    before = "2026-10-31T00:00:00Z"
    _check(edits=[_edit(before, LOOKALIKE_ID)], last_edited_at=before)


def test_a_stranger_edit_after_the_label_is_refused() -> None:
    with pytest.raises(TrustError, match="edited"):
        _check(edits=[_edit(T1, 99)], last_edited_at=T1)


def test_a_lookalike_id_edit_after_the_label_is_refused() -> None:
    with pytest.raises(TrustError):
        _check(edits=[_edit(T1, LOOKALIKE_ID)], last_edited_at=T1)


def test_an_owner_edit_after_the_label_is_fine() -> None:
    _check(edits=[_edit(T1, OWNER_ID)], last_edited_at=T1)


def test_a_stranger_edit_hiding_among_owner_edits_is_refused() -> None:
    with pytest.raises(TrustError):
        _check(edits=[_edit(T1, OWNER_ID), _edit(T2, 99)], last_edited_at=T2)


def test_an_edit_with_no_known_editor_is_refused() -> None:
    with pytest.raises(TrustError):
        _check(edits=[_edit(T1, None)], last_edited_at=T1)


def test_a_last_edit_the_history_does_not_explain_is_refused() -> None:
    # lastEditedAt says it changed again at T2 but the history stops at T1 (deleted or hidden)
    with pytest.raises(TrustError, match="history"):
        _check(edits=[_edit(T1, OWNER_ID)], last_edited_at=T2)


def test_an_edit_with_no_history_at_all_is_refused() -> None:
    with pytest.raises(TrustError, match="history"):
        _check(edits=[], last_edited_at=T1)


def test_a_stranger_author_is_refused() -> None:
    with pytest.raises(TrustError, match="author"):
        _check(issue=_issue(LOOKALIKE_ID))


def test_no_ready_label_event_is_refused() -> None:
    with pytest.raises(TrustError, match="ready-for-agent"):
        _check(events=[_labeled(T0, name="bug")])


def test_a_label_removed_again_is_refused() -> None:
    gone = {
        "event": "unlabeled",
        "created_at": T1,
        "actor": {"id": OWNER_ID},
        "label": {"name": "ready-for-agent"},
    }
    with pytest.raises(TrustError, match="ready-for-agent"):
        _check(events=[_labeled(T0), gone])


def test_a_label_applied_by_a_stranger_is_refused() -> None:
    with pytest.raises(TrustError, match="owner"):
        _check(events=[_labeled(T0, actor=LOOKALIKE_ID)])


def test_reapplying_the_label_resets_the_window() -> None:
    _check(events=[_labeled(T0), _labeled(T2)], edits=[_edit(T1, 99)], last_edited_at=T1)


def test_a_rename_by_a_stranger_after_the_label_is_refused() -> None:
    renamed = {"event": "renamed", "created_at": T1, "actor": {"id": 99}}
    with pytest.raises(TrustError, match="renamed"):
        _check(events=[_labeled(T0), renamed])


def test_a_rename_by_the_owner_is_fine() -> None:
    renamed = {"event": "renamed", "created_at": T1, "actor": {"id": OWNER_ID}}
    _check(events=[_labeled(T0), renamed])


def test_an_event_with_a_bad_time_or_actor_is_an_error() -> None:
    with pytest.raises(TrustError):
        _check(events=[{"event": "labeled", "created_at": "yesterday", "actor": {"id": 1}}])
    with pytest.raises(TrustError):
        _check(events=[{"event": "renamed", "created_at": T1, "actor": None}, _labeled(T0)])
