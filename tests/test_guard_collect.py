"""Collecting the guard's inputs from GitHub, and failing closed when they are incomplete."""

from typing import Any

import pytest

from guard import rules
from guard.collect import GuardError, collect
from guard.run import run

REPO = "o/r"
BASE = "b" * 40
HEAD = "1" * 40
MERGE_BASE = "2" * 40


class FakeApi:
    """Answers GitHub API paths from a dict. A missing path is a test bug, not a 404."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def get_json(self, path: str) -> Any:
        self.requested.append(path)
        return self.routes[path]

    def get_pages(self, path: str) -> list[Any]:
        self.requested.append(path)
        return list(self.routes[path])

    def get_text(self, path: str) -> str | None:
        self.requested.append(path)
        return self.routes.get(path)


def _pr(**over: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 7,
        "user": {"id": 999},
        "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "repo": {"full_name": REPO}},
        "changed_files": 1,
    }
    pr.update(over)
    return pr


def _routes(
    files: list[dict[str, Any]],
    pr: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routes: dict[str, Any] = {
        f"/repos/{REPO}/pulls/7": pr or _pr(changed_files=len(files)),
        f"/repos/{REPO}/pulls/7/files": files,
        f"/repos/{REPO}/pulls/7/reviews": [],
        f"/repos/{REPO}/compare/{BASE}...{HEAD}": {"merge_base_commit": {"sha": MERGE_BASE}},
        f"/repos/{REPO}/git/trees/{MERGE_BASE}?recursive=1": {"truncated": False, "tree": []},
        f"/repos/{REPO}/git/trees/{HEAD}?recursive=1": {"truncated": False, "tree": []},
    }
    routes.update(extra or {})
    return routes


def _file(name: str, **over: Any) -> dict[str, Any]:
    return {"filename": name, "status": "modified", "patch": "@@ x", **over}


def test_collects_a_plain_pr() -> None:
    api = FakeApi(_routes([_file("src/a.py")]))
    pr, files, reviews, snapshot = collect(api, REPO, 7)
    assert pr.author_id == 999
    assert pr.head_sha == HEAD
    assert [f.path for f in files] == ["src/a.py"]
    assert reviews == []
    assert snapshot.symlinks == frozenset()
    # contents are only read when pyproject.toml or uv.lock changed
    assert not any("/contents/" in p for p in api.requested)


def test_reads_pyproject_and_lock_at_merge_base_and_head_when_they_change() -> None:
    routes = _routes(
        [_file("pyproject.toml"), _file("uv.lock")],
        extra={
            f"/repos/{REPO}/contents/pyproject.toml?ref={MERGE_BASE}": "base-py",
            f"/repos/{REPO}/contents/pyproject.toml?ref={HEAD}": "head-py",
            f"/repos/{REPO}/contents/uv.lock?ref={MERGE_BASE}": "base-lock",
            f"/repos/{REPO}/contents/uv.lock?ref={HEAD}": "head-lock",
        },
    )
    _, _, _, snapshot = collect(FakeApi(routes), REPO, 7)
    assert (snapshot.pyproject_base, snapshot.pyproject_head) == ("base-py", "head-py")
    assert (snapshot.lock_base, snapshot.lock_head) == ("base-lock", "head-lock")


def test_symlinks_come_from_both_trees() -> None:
    routes = _routes(
        [_file("a"), _file("b")],
        extra={
            f"/repos/{REPO}/git/trees/{HEAD}?recursive=1": {
                "truncated": False,
                "tree": [{"path": "a", "mode": "120000"}, {"path": "c", "mode": "100644"}],
            },
            f"/repos/{REPO}/git/trees/{MERGE_BASE}?recursive=1": {
                "truncated": False,
                "tree": [{"path": "b", "mode": "120000"}],
            },
        },
    )
    _, _, _, snapshot = collect(FakeApi(routes), REPO, 7)
    assert snapshot.symlinks == frozenset({"a", "b"})


def test_renames_carry_the_previous_path() -> None:
    f = _file("new.md", status="renamed", previous_filename="docs/adr/old.md")
    _, files, _, _ = collect(FakeApi(_routes([f])), REPO, 7)
    assert files[0].previous_path == "docs/adr/old.md"


def test_reviews_are_collected_with_their_commit() -> None:
    review = {"user": {"id": 754466}, "state": "APPROVED", "commit_id": HEAD}
    ghost = {"user": None, "state": "APPROVED", "commit_id": HEAD}
    routes = _routes([_file("a")], extra={f"/repos/{REPO}/pulls/7/reviews": [review, ghost]})
    _, _, reviews, _ = collect(FakeApi(routes), REPO, 7)
    assert reviews == [rules.Review(754466, "APPROVED", HEAD)]


# --- fail closed ---------------------------------------------------------------------------


def test_fewer_files_than_the_pr_reports_means_truncation() -> None:
    routes = _routes([_file("a")], pr=_pr(changed_files=2))
    with pytest.raises(GuardError, match="truncat"):
        collect(FakeApi(routes), REPO, 7)


def test_prs_at_githubs_file_listing_limit_cannot_be_judged() -> None:
    files = [_file(f"f{i}") for i in range(3000)]
    routes = _routes(files, pr=_pr(changed_files=3000))
    with pytest.raises(GuardError, match="3000"):
        collect(FakeApi(routes), REPO, 7)


@pytest.mark.parametrize("which", ["head", "merge-base"])
def test_a_truncated_tree_cannot_be_judged(which: str) -> None:
    sha = HEAD if which == "head" else MERGE_BASE
    routes = _routes(
        [_file("a")],
        extra={f"/repos/{REPO}/git/trees/{sha}?recursive=1": {"truncated": True, "tree": []}},
    )
    with pytest.raises(GuardError, match="truncat"):
        collect(FakeApi(routes), REPO, 7)


def test_a_missing_head_repo_cannot_be_judged() -> None:
    pr = _pr(head={"sha": HEAD, "ref": "x", "repo": None})
    with pytest.raises(GuardError, match="head repository"):
        collect(FakeApi(_routes([_file("a")], pr=pr)), REPO, 7)


@pytest.mark.parametrize(
    "bad_pr",
    [
        {"user": None},
        {"user": {"id": "999"}},
        {"head": {"sha": "not-a-sha", "ref": "x", "repo": {"full_name": REPO}}},
        {"changed_files": "1"},
    ],
)
def test_malformed_pr_data_cannot_be_judged(bad_pr: dict[str, Any]) -> None:
    with pytest.raises(GuardError):
        collect(FakeApi(_routes([_file("a")], pr=_pr(**bad_pr))), REPO, 7)


def test_a_file_entry_without_a_name_cannot_be_judged() -> None:
    with pytest.raises(GuardError):
        collect(FakeApi(_routes([{"status": "modified"}])), REPO, 7)


def test_an_unreadable_changed_pyproject_cannot_be_judged() -> None:
    # pyproject.toml changed but the head copy is unreadable: refuse to guess.
    routes = _routes(
        [_file("pyproject.toml")],
        extra={f"/repos/{REPO}/contents/pyproject.toml?ref={MERGE_BASE}": "base"},
    )
    _, _, _, snapshot = collect(FakeApi(routes), REPO, 7)
    assert snapshot.pyproject_head is None  # None means "no such file", judged as a change


# --- the entry point -------------------------------------------------------------------------


def _env(**over: str) -> dict[str, str]:
    return {"GUARD_REPO": REPO, "GUARD_PR": "7", **over}


def test_run_passes_an_unguarded_pr(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(_env(), FakeApi(_routes([_file("src/a.py")]))) == 0
    assert "passed" in capsys.readouterr().out


def test_run_fails_a_guarded_pr_by_a_stranger(capsys: pytest.CaptureFixture[str]) -> None:
    code = run(_env(), FakeApi(_routes([_file(".github/workflows/ci.yml")])))
    assert code == 1
    assert ".github/workflows/ci.yml" in capsys.readouterr().out


def test_run_passes_a_guarded_pr_written_by_the_owner() -> None:
    pr = _pr(user={"id": rules.OWNER_ID})
    assert run(_env(), FakeApi(_routes([_file("AGENTS.md")], pr=pr))) == 0


def test_run_fails_when_anything_goes_wrong() -> None:
    class Broken(FakeApi):
        def get_json(self, path: str) -> Any:
            raise OSError("network down")

    assert run(_env(), Broken({})) != 0


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"GUARD_REPO": REPO},
        {"GUARD_PR": "7"},
        {"GUARD_REPO": "no-slash", "GUARD_PR": "7"},
        {"GUARD_REPO": REPO, "GUARD_PR": "seven"},
        {"GUARD_REPO": "o/r; rm -rf", "GUARD_PR": "7"},
    ],
)
def test_run_fails_on_missing_or_malformed_configuration(env: dict[str, str]) -> None:
    assert run(env, FakeApi(_routes([_file("a")]))) != 0


def test_hostile_file_names_cannot_start_a_workflow_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    name = ".github/x\n::error::pwned"
    run(_env(), FakeApi(_routes([_file(name)])))
    assert not any(line.startswith("::") for line in capsys.readouterr().out.splitlines())
