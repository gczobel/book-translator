"""Release-tag verification: a tag must point at a release-please merge commit on main."""

from dataclasses import replace
from typing import Any

import pytest

from ghapi.identities import AGENT_BOT_ID, DEPENDABOT_ID, MAINT_BOT_ID
from releasetag.core import MergedPull, TagFacts, verify

REPO = "o/r"
SHA = "a" * 40


def pull(**over: Any) -> MergedPull:
    base = MergedPull(
        number=7,
        author_id=MAINT_BOT_ID,
        head_repo=REPO,
        base_repo=REPO,
        head_ref="release-please--branches--main",
        base_ref="main",
        merge_commit_sha=SHA,
        merged=True,
        title="chore: release 1.2.3",
    )
    return replace(base, **over)


def facts(**over: Any) -> TagFacts:
    base = TagFacts(tag="v1.2.3", commit_sha=SHA, on_main=True, parent_count=1, pulls=(pull(),))
    return replace(base, **over)


def test_a_release_please_merge_on_main_is_accepted() -> None:
    assert verify(facts(), REPO, "main").ok


@pytest.mark.parametrize(
    "tag", ["v1.2", "1.2.3", "v1.2.3-rc1", "v01.2.3", "v1.2.3\n", "vx.y.z", ""]
)
def test_a_malformed_tag_name_is_rejected(tag: str) -> None:
    assert not verify(facts(tag=tag), REPO, "main").ok


def test_a_commit_not_reachable_from_main_is_rejected() -> None:
    assert not verify(facts(on_main=False), REPO, "main").ok


def test_a_merge_commit_with_two_parents_is_rejected() -> None:
    assert not verify(facts(parent_count=2), REPO, "main").ok


def test_a_commit_with_no_pull_request_is_rejected() -> None:
    assert not verify(facts(pulls=()), REPO, "main").ok


@pytest.mark.parametrize("author", [DEPENDABOT_ID, AGENT_BOT_ID, 754466])
def test_a_pull_request_by_anyone_but_the_maintenance_app_is_rejected(author: int) -> None:
    assert not verify(facts(pulls=(pull(author_id=author),)), REPO, "main").ok


@pytest.mark.parametrize(
    "over",
    [
        {"head_ref": "feature/x"},
        {"head_ref": "release-please-branches-main"},
        {"head_repo": "evil/r"},
        {"head_repo": None},
        {"base_repo": "evil/r"},
        {"base_ref": "dev"},
        {"merged": False},
        {"merge_commit_sha": "b" * 40},
        {"title": "chore: release 9.9.9"},
        {"title": "feat: something"},
    ],
)
def test_a_pull_request_that_is_not_the_release_pull_request_is_rejected(
    over: dict[str, Any],
) -> None:
    assert not verify(facts(pulls=(pull(**over),)), REPO, "main").ok


def test_two_associated_pull_requests_are_rejected() -> None:
    assert not verify(facts(pulls=(pull(), pull(number=8))), REPO, "main").ok


def test_an_extra_bad_pull_request_does_not_hide_behind_a_good_one() -> None:
    bad = pull(number=9, author_id=DEPENDABOT_ID)
    assert not verify(facts(pulls=(pull(), bad)), REPO, "main").ok
