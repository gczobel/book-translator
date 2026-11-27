"""Collecting the merge rule's inputs, and the entry point that publishes the decision."""

from pathlib import Path
from typing import Any

import pytest

from agentpr import collect
from agentpr.collect import AgentPrError
from agentpr.core import ACTIONS_APP_ID, REQUIRED_CHECKS
from agentpr.run import run
from ghapi.identities import AGENT_BOT_ID, OWNER_ID

REPO = "o/r"
SHA = "1" * 40


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


def _raw_pr(**over: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 7,
        "state": "open",
        "merged": False,
        "draft": False,
        "user": {"id": AGENT_BOT_ID, "type": "Bot"},
        "head": {"sha": SHA, "ref": "agent/x", "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO, "default_branch": "main"}},
        "labels": [],
        "changed_files": 1,
    }
    pr.update(over)
    return pr


def _check_pages(
    names: tuple[str, ...] = REQUIRED_CHECKS, conclusion: str = "success"
) -> dict[str, Any]:
    runs = [
        {
            "id": i,
            "name": n,
            "status": "completed",
            "conclusion": conclusion,
            "app": {"id": ACTIONS_APP_ID},
        }
        for i, n in enumerate(names, start=1)
    ]
    return {"total_count": len(runs), "check_runs": runs}


def _routes(**over: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {
        f"/repos/{REPO}/pulls?state=open": [_raw_pr()],
        f"/repos/{REPO}/git/matching-refs/tags/v": [],
        f"/repos/{REPO}/pulls/7": _raw_pr(),
        f"/repos/{REPO}/pulls/7/reviews": [],
        f"/repos/{REPO}/pulls/7/files": [{"filename": "src/a.py"}],
        f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=1": _check_pages(),
    }
    routes.update(over)
    return routes


def _run(tmp_path: Path, api: FakeApi, **env: str) -> tuple[int, str]:
    out = tmp_path / "out"
    out.write_text("")
    environment = {"AGENTPR_REPO": REPO, "GITHUB_OUTPUT": str(out), **env}
    code = run(environment, api)
    return code, out.read_text()


def test_a_ready_agent_pr_is_published_for_merging(tmp_path: Path) -> None:
    code, out = _run(tmp_path, FakeApi(_routes()))
    assert code == 0
    assert out.splitlines() == ["merge=true", "pr=7", f"sha={SHA}"]


def test_the_event_commit_is_ignored_so_a_base_tip_head_sha_still_finds_the_pr(
    tmp_path: Path,
) -> None:
    code, out = _run(tmp_path, FakeApi(_routes()), AGENTPR_SHA="9" * 40, AGENTPR_PR="99")
    assert code == 0
    assert out.splitlines() == ["merge=true", "pr=7", f"sha={SHA}"]


def test_a_failing_check_is_not_an_error_just_no_merge(tmp_path: Path) -> None:
    routes = _routes(
        **{
            f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=1": _check_pages(
                conclusion="failure"
            )
        }
    )
    code, out = _run(tmp_path, FakeApi(routes))
    assert (code, out.strip()) == (0, "merge=false")


def test_another_authors_pr_is_skipped_without_reading_its_files(tmp_path: Path) -> None:
    other = _raw_pr(user={"id": OWNER_ID, "type": "User"})
    api = FakeApi(_routes(**{f"/repos/{REPO}/pulls?state=open": [other]}))
    code, out = _run(tmp_path, api)
    assert (code, out.strip()) == (0, "merge=false")
    assert not any("/files" in p or "check-runs" in p for p in api.requested)


def test_no_open_pr_merges_nothing(tmp_path: Path) -> None:
    api = FakeApi(_routes(**{f"/repos/{REPO}/pulls?state=open": []}))
    assert _run(tmp_path, api) == (0, "merge=false\n")


def test_only_agent_app_prs_are_listed_lowest_number_first() -> None:
    other = _raw_pr(number=3, user={"id": OWNER_ID, "type": "User"})
    listing = [_raw_pr(number=9), other, _raw_pr(number=5)]
    api = FakeApi(_routes(**{f"/repos/{REPO}/pulls?state=open": listing}))
    assert collect.agent_pr_numbers(api, REPO) == [5, 9]


def _second_pr_routes(**over: Any) -> dict[str, Any]:
    sha2 = "3" * 40
    head = {"sha": sha2, "ref": "agent/y", "repo": {"full_name": REPO}}
    return _routes(
        **{
            f"/repos/{REPO}/pulls?state=open": [_raw_pr(), _raw_pr(number=8, head=head)],
            f"/repos/{REPO}/pulls/8": _raw_pr(number=8, head=head),
            f"/repos/{REPO}/pulls/8/reviews": [],
            f"/repos/{REPO}/pulls/8/files": [{"filename": "src/b.py"}],
            f"/repos/{REPO}/commits/{sha2}/check-runs?per_page=100&page=1": _check_pages(),
            **over,
        }
    )


def test_with_two_ready_prs_exactly_the_lowest_is_published(tmp_path: Path) -> None:
    code, out = _run(tmp_path, FakeApi(_second_pr_routes()))
    assert code == 0
    assert out.splitlines() == ["merge=true", "pr=7", f"sha={SHA}"]


def test_a_blocked_first_pr_does_not_hide_a_ready_second_one(tmp_path: Path) -> None:
    held = _raw_pr(labels=[{"name": "hold"}])
    code, out = _run(tmp_path, FakeApi(_second_pr_routes(**{f"/repos/{REPO}/pulls/7": held})))
    assert code == 0
    assert out.splitlines()[:2] == ["merge=true", "pr=8"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(
            {f"/repos/{REPO}/pulls/7": _raw_pr(head={"sha": SHA, "ref": "agent/x", "repo": None})}
        ),
        lambda r: r.update({f"/repos/{REPO}/pulls/7": _raw_pr(draft="no")}),
        lambda r: r.update({f"/repos/{REPO}/pulls/7": _raw_pr(labels=None)}),
        lambda r: r.update({f"/repos/{REPO}/pulls/7": _raw_pr(changed_files=2)}),  # truncated list
        lambda r: r.update({f"/repos/{REPO}/pulls/7": _raw_pr(changed_files=3000)}),
        lambda r: r.update(
            {
                f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=1": {
                    "total_count": 20,
                    "check_runs": [],
                }
            }
        ),
        lambda r: r.update({f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=1": []}),
    ],
)
def test_incomplete_or_odd_data_fails_closed(tmp_path: Path, mutate: Any) -> None:
    routes = _routes()
    mutate(routes)
    code, out = _run(tmp_path, FakeApi(routes))
    assert code == 2
    assert "merge=true" not in out


def test_a_rename_out_of_a_guarded_path_blocks(tmp_path: Path) -> None:
    renamed = [{"filename": "src/new.md", "previous_filename": ".github/workflows/ci.yml"}]
    code, out = _run(tmp_path, FakeApi(_routes(**{f"/repos/{REPO}/pulls/7/files": renamed})))
    assert (code, out.strip()) == (0, "merge=false")


def test_check_runs_are_read_across_pages() -> None:
    first = _check_pages(REQUIRED_CHECKS[:5])
    second = _check_pages(REQUIRED_CHECKS[5:])
    first["total_count"] = second["total_count"] = len(REQUIRED_CHECKS)
    for i, c in enumerate(second["check_runs"], start=100):
        c["id"] = i
    api = FakeApi(
        {
            f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=1": first,
            f"/repos/{REPO}/commits/{SHA}/check-runs?per_page=100&page=2": second,
        }
    )
    assert len(collect.check_runs(api, REPO, SHA)) == len(REQUIRED_CHECKS)


def test_only_the_owners_reviews_count(tmp_path: Path) -> None:
    reviews = [
        {"user": {"id": 5}, "state": "CHANGES_REQUESTED"},
        {"user": None, "state": "CHANGES_REQUESTED"},
        {"user": {"id": OWNER_ID}, "state": "COMMENTED"},
    ]
    code, out = _run(tmp_path, FakeApi(_routes(**{f"/repos/{REPO}/pulls/7/reviews": reviews})))
    assert (code, out.splitlines()[0]) == (0, "merge=true")
    blocked = [{"user": {"id": OWNER_ID}, "state": "CHANGES_REQUESTED", "commit_id": SHA}]
    code, out = _run(tmp_path, FakeApi(_routes(**{f"/repos/{REPO}/pulls/7/reviews": blocked})))
    assert (code, out.strip()) == (0, "merge=false")


def _guarded_routes(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    return _routes(
        **{
            f"/repos/{REPO}/pulls/7/files": [{"filename": "AGENTS.md"}],
            f"/repos/{REPO}/pulls/7/reviews": reviews,
        }
    )


def _approval(
    reviewer: int = OWNER_ID, commit: str = SHA, state: str = "APPROVED"
) -> dict[str, Any]:
    return {"user": {"id": reviewer}, "state": state, "commit_id": commit}


@pytest.mark.parametrize(
    ("reviews", "merges"),
    [
        ([_approval()], True),  # approval on the head
        ([_approval(commit="2" * 40)], False),  # approval on an old commit
        ([_approval(reviewer=OWNER_ID + 1)], False),  # a look-alike ID, not the owner
        ([_approval(state="DISMISSED")], False),  # dismissed approval
        ([], False),  # no review
    ],
)
def test_guarded_paths_merge_only_on_the_owners_approval_of_the_head(
    tmp_path: Path, reviews: list[dict[str, Any]], merges: bool
) -> None:
    code, out = _run(tmp_path, FakeApi(_guarded_routes(reviews)))
    assert code == 0
    assert out.startswith("merge=true") is merges


def test_an_owner_review_without_a_readable_commit_fails_closed(tmp_path: Path) -> None:
    for bad in (None, "abc", 7):
        review = {"user": {"id": OWNER_ID}, "state": "APPROVED", "commit_id": bad}
        code, out = _run(tmp_path, FakeApi(_guarded_routes([review])))
        assert code == 2 and "merge=true" not in out


def test_a_malformed_environment_fails_closed(tmp_path: Path) -> None:
    api = FakeApi(_routes())
    assert _run(tmp_path, api, AGENTPR_REPO="not a repo")[0] == 2
    assert run({"AGENTPR_REPO": REPO}, api) == 2  # no GITHUB_OUTPUT
    assert run({"AGENTPR_REPO": REPO, "GITHUB_OUTPUT": str(tmp_path / "o")}) == 2


def test_an_api_error_fails_closed(tmp_path: Path) -> None:
    class Broken(FakeApi):
        def get_json(self, path: str) -> Any:
            raise TimeoutError

    assert _run(tmp_path, Broken(_routes()))[0] == 2


def test_collect_error_is_importable() -> None:
    with pytest.raises(AgentPrError):
        collect.require_repo("..", "x")


def test_a_release_tag_stops_the_merge(tmp_path: Path) -> None:
    tags = [{"ref": "refs/tags/v0.1.0"}]
    code, out = _run(
        tmp_path, FakeApi(_routes(**{f"/repos/{REPO}/git/matching-refs/tags/v": tags}))
    )
    assert (code, out.strip()) == (0, "merge=false")


@pytest.mark.parametrize("bad", [[{"ref": "refs/heads/v1"}], [{"ref": 5}], ["x"]])
def test_unreadable_tags_fail_the_job_closed(tmp_path: Path, bad: list[Any]) -> None:
    code, out = _run(tmp_path, FakeApi(_routes(**{f"/repos/{REPO}/git/matching-refs/tags/v": bad})))
    assert code == 2 and "merge=true" not in out
