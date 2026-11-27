"""The tag-verification entry point, against a fake GitHub."""

from pathlib import Path
from typing import Any

import pytest

from ghapi.client import ApiError
from ghapi.identities import DEPENDABOT_ID, MAINT_BOT_ID
from releasetag.run import run

REPO = "o/r"
SHA = "a" * 40
TAG_OBJECT = "c" * 40


def github_pull(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": 7,
        "user": {"id": MAINT_BOT_ID},
        "head": {"ref": "release-please--branches--main", "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "merge_commit_sha": SHA,
        "merged_at": "2026-11-27T12:00:00Z",
        "title": "chore: release 1.2.3",
    }
    base.update(over)
    return base


class FakeGitHub:
    def __init__(
        self,
        pulls: list[list[dict[str, Any]]] | None = None,
        status: str = "behind",
        parents: int = 1,
        annotated: bool = False,
        fail: bool = False,
    ) -> None:
        self.pulls = pulls if pulls is not None else [[github_pull()]]
        self.status = status
        self.parents = parents
        self.annotated = annotated
        self.fail = fail
        self.paths: list[str] = []

    def get_json(self, path: str) -> Any:
        self.paths.append(path)
        if self.fail:
            raise ApiError("boom")
        if path == f"/repos/{REPO}/git/ref/tags/v1.2.3":
            if self.annotated:
                return {"object": {"type": "tag", "sha": TAG_OBJECT}}
            return {"object": {"type": "commit", "sha": SHA}}
        if path == f"/repos/{REPO}/git/tags/{TAG_OBJECT}":
            return {"object": {"type": "commit", "sha": SHA}}
        if path == f"/repos/{REPO}/commits/{SHA}":
            return {"sha": SHA, "parents": [{"sha": "p"}] * self.parents}
        if path == f"/repos/{REPO}/compare/main...{SHA}?per_page=1":
            return {"status": self.status}
        raise AssertionError(path)

    def get_pages(self, path: str) -> list[Any]:
        self.paths.append(path)
        if self.fail:
            raise ApiError("boom")
        assert path == f"/repos/{REPO}/commits/{SHA}/pulls"
        return self.pulls.pop(0) if len(self.pulls) > 1 else self.pulls[0]


def env(tmp_path: Path, **over: str) -> dict[str, str]:
    base = {
        "GITHUB_REPOSITORY": REPO,
        "TAG_NAME": "v1.2.3",
        "REF_TYPE": "tag",
        "DEFAULT_BRANCH": "main",
        "GITHUB_OUTPUT": str(tmp_path / "out"),
    }
    base.update(over)
    return base


def go(api: FakeGitHub, environment: dict[str, str]) -> int:
    return run(environment, api=api, sleep=lambda _s: None)


def test_a_release_please_tag_passes(tmp_path: Path) -> None:
    assert go(FakeGitHub(), env(tmp_path)) == 0


def test_an_annotated_tag_is_peeled_to_its_commit(tmp_path: Path) -> None:
    assert go(FakeGitHub(annotated=True), env(tmp_path)) == 0


def test_the_tagged_commit_itself_being_main_counts_as_on_main(tmp_path: Path) -> None:
    assert go(FakeGitHub(status="identical"), env(tmp_path)) == 0


@pytest.mark.parametrize("status", ["ahead", "diverged", "", "weird"])
def test_a_commit_not_behind_main_fails(tmp_path: Path, status: str) -> None:
    assert go(FakeGitHub(status=status), env(tmp_path)) == 1


def test_a_dependabot_pull_request_fails(tmp_path: Path) -> None:
    pulls = [[github_pull(user={"id": DEPENDABOT_ID})]]
    assert go(FakeGitHub(pulls=pulls), env(tmp_path)) == 1


def test_a_pull_request_with_a_deleted_fork_fails(tmp_path: Path) -> None:
    pulls = [[github_pull(head={"ref": "release-please--branches--main", "repo": None})]]
    assert go(FakeGitHub(pulls=pulls), env(tmp_path)) == 1


def test_a_pull_request_not_yet_associated_is_retried(tmp_path: Path) -> None:
    api = FakeGitHub(pulls=[[], [], [github_pull()]])
    assert go(api, env(tmp_path)) == 0


def test_a_commit_that_never_gets_a_pull_request_fails(tmp_path: Path) -> None:
    assert go(FakeGitHub(pulls=[[]]), env(tmp_path)) == 1


def test_a_squash_merge_is_required(tmp_path: Path) -> None:
    assert go(FakeGitHub(parents=2), env(tmp_path)) == 1


def test_an_api_error_fails_closed(tmp_path: Path) -> None:
    assert go(FakeGitHub(fail=True), env(tmp_path)) == 1


@pytest.mark.parametrize("tag", ["v1.2.3/../../x", "v1.2", "v1.2.3?x=1", ""])
def test_a_malformed_tag_fails_without_calling_the_api(tmp_path: Path, tag: str) -> None:
    api = FakeGitHub()
    assert go(api, env(tmp_path, TAG_NAME=tag)) == 1
    assert api.paths == []


def test_a_branch_creation_fails(tmp_path: Path) -> None:
    assert go(FakeGitHub(), env(tmp_path, REF_TYPE="branch")) == 1


@pytest.mark.parametrize("missing", ["GITHUB_REPOSITORY", "TAG_NAME", "REF_TYPE", "DEFAULT_BRANCH"])
def test_a_missing_input_fails(tmp_path: Path, missing: str) -> None:
    environment = env(tmp_path)
    del environment[missing]
    assert go(FakeGitHub(), environment) == 1


def test_a_malformed_repository_fails(tmp_path: Path) -> None:
    assert go(FakeGitHub(), env(tmp_path, GITHUB_REPOSITORY="not a repo")) == 1
