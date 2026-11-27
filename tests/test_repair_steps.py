"""The repair workflow's steps against a fake GitHub and real git. Seam: `repair.run`."""

import base64
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ghapi.client import ApiError
from ghapi.identities import DEPENDABOT_ID
from repair.run import build, names, push, select

REPO = "o/r"
SHA = "c" * 40


def raw_pull(**over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "number": 7,
        "node_id": "PR_7",
        "state": "open",
        "user": {"id": DEPENDABOT_ID},
        "head": {"repo": {"full_name": REPO}, "ref": "dependabot/uv/x-1", "sha": SHA},
        "base": {"repo": {"full_name": REPO}, "ref": "main"},
        "labels": [],
        "auto_merge": None,
    }
    item.update(over)
    return item


class FakeApi:
    def __init__(self) -> None:
        self.pulls: list[dict[str, Any]] = [raw_pull()]
        self.messages: list[str] = ["Bump x from 1 to 2"]
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.graphql_reply: Any = {"data": {"createCommitOnBranch": {"commit": {"oid": "d" * 40}}}}
        self.fail = False

    def get_json(self, path: str) -> Any:
        raise AssertionError(path)

    def get_text(self, path: str) -> str | None:
        raise AssertionError(path)

    def get_pages(self, path: str) -> list[Any]:
        if self.fail:
            raise ApiError("down")
        if path == f"/repos/{REPO}/commits/{SHA}/pulls":
            return self.pulls
        if path == f"/repos/{REPO}/pulls/7/commits":
            return [{"commit": {"message": m + "\n\nbody"}} for m in self.messages]
        raise AssertionError(path)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        self.posts.append((path, payload))
        return self.graphql_reply


def select_env(tmp_path: Path, **over: str) -> dict[str, str]:
    env = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "REPAIR_RUN_SHA": SHA,
        "REPAIR_RUN_CONCLUSION": "failure",
        "REPAIR_RUN_EVENT": "pull_request",
    }
    env.update(over)
    return env


def outputs(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / "out").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_a_failed_run_on_a_dependabot_pr_selects_the_first_attempt(tmp_path: Path) -> None:
    assert select(select_env(tmp_path), FakeApi()) == 0
    out = outputs(tmp_path)
    assert out["action"] == "repair"
    assert (out["pr"], out["head_sha"], out["attempt"], out["ok"]) == ("7", SHA, "1", "true")
    assert out["head_ref"] == "dependabot/uv/x-1"


def test_a_commit_to_main_with_no_pr_is_skipped_quietly(tmp_path: Path) -> None:
    api = FakeApi()
    api.pulls = []
    assert select(select_env(tmp_path), api) == 0
    assert outputs(tmp_path)["action"] == "skip"
    assert outputs(tmp_path)["ok"] == "true"


def test_two_open_prs_for_one_commit_are_skipped(tmp_path: Path) -> None:
    api = FakeApi()
    api.pulls = [raw_pull(), raw_pull(number=8)]
    select(select_env(tmp_path), api)
    assert outputs(tmp_path)["action"] == "skip"


def test_a_run_not_caused_by_a_pull_request_is_skipped(tmp_path: Path) -> None:
    select(select_env(tmp_path, REPAIR_RUN_EVENT="push"), FakeApi())
    assert outputs(tmp_path)["action"] == "skip"


def test_a_spent_budget_selects_an_escalation(tmp_path: Path) -> None:
    api = FakeApi()
    api.messages = ["Bump", "repair: automated fix", "repair: automated fix"]
    select(select_env(tmp_path), api)
    out = outputs(tmp_path)
    assert (out["action"], out["reason"], out["pr"]) == (
        "escalate",
        "repair-attempts-exhausted",
        "7",
    )


def test_an_api_failure_publishes_not_ok_so_it_escalates(tmp_path: Path) -> None:
    api = FakeApi()
    api.fail = True
    assert select(select_env(tmp_path), api) == 0
    out = outputs(tmp_path)
    assert (out["ok"], out["action"]) == ("false", "skip")


def test_an_odd_branch_name_is_not_passed_on(tmp_path: Path) -> None:
    api = FakeApi()
    api.pulls = [raw_pull(head={"repo": {"full_name": REPO}, "ref": "a b;c", "sha": SHA})]
    select(select_env(tmp_path), api)
    out = outputs(tmp_path)
    assert (out["ok"], out["action"]) == ("false", "skip")


# --- build / names / push, on a real repository ---


def sh(directory: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    done = subprocess.run(
        ["git", *args], cwd=directory, env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


PYPROJECT = '[project]\nname = "x"\ndependencies = ["httpx>=0.27"]\n'
LOCK = '[[package]]\nname = "httpx"\nversion = "1"\n'


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    d = tmp_path / "repo"
    d.mkdir()
    sh(d, "init", "-q", "-b", "main")
    (d / "src").mkdir()
    (d / "src" / "a.py").write_text("x = 1\n")
    (d / "pyproject.toml").write_text(PYPROJECT)
    (d / "uv.lock").write_text(LOCK)
    sh(d, "add", "-A")
    sh(d, "commit", "-q", "-m", "base")
    base = sh(d, "rev-parse", "HEAD").strip()
    (d / "src" / "a.py").write_text("x = 2\n")
    sh(d, "add", "-A")
    patch = sh(d, "diff", "--cached", "--no-renames", "--full-index")
    sh(d, "reset", "-q", "--hard", base)
    return d, base, base64.b64encode(patch.encode()).decode()


def test_build_publishes_the_commit_and_tree(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    d, base, patch = repo
    env = {
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "REPAIR_DIR": str(d),
        "REPAIR_BASE": base,
        "REPAIR_PATCH_B64": patch,
        "REPAIR_ATTEMPT": "1",
    }
    assert build(env) == 0
    out = outputs(tmp_path)
    assert sh(d, "rev-parse", f"{out['head']}^{{tree}}").strip() == out["tree"]
    assert sh(d, "log", "-1", "--format=%s", out["head"]).startswith("repair: ")


def test_build_fails_closed_on_garbage(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    d, base, _ = repo
    env = {
        "REPAIR_DIR": str(d),
        "REPAIR_BASE": base,
        "REPAIR_PATCH_B64": "!!notbase64!!",
        "REPAIR_ATTEMPT": "1",
    }
    assert build(env) == 2
    assert build({**env, "REPAIR_PATCH_B64": ""}) == 2


def commit_with(d: Path, base: str, files: dict[str, str]) -> str:
    sh(d, "checkout", "-q", "--detach", base)
    for path, text in files.items():
        (d / path).parent.mkdir(parents=True, exist_ok=True)
        (d / path).write_text(text)
    sh(d, "add", "-A")
    sh(d, "commit", "-q", "-m", "head")
    return sh(d, "rev-parse", "HEAD").strip()


def names_env(d: Path, base: str, head: str) -> dict[str, str]:
    return {"REPAIR_DIR": str(d), "REPAIR_BASE": base, "REPAIR_HEAD": head}


def test_names_accepts_a_repair_that_adds_no_dependency_name(
    repo: tuple[Path, str, str],
) -> None:
    d, base, _ = repo
    head = commit_with(d, base, {"pyproject.toml": PYPROJECT.replace("0.27", "0.28")})
    assert names(names_env(d, base, head)) == 0


def test_names_rejects_a_new_name_in_either_file(repo: tuple[Path, str, str]) -> None:
    d, base, _ = repo
    in_toml = commit_with(d, base, {"pyproject.toml": PYPROJECT.replace('"]', '", "httpxx"]')})
    assert names(names_env(d, base, in_toml)) == 1
    in_lock = commit_with(d, base, {"uv.lock": LOCK + '\n[[package]]\nname = "httpxx"\n'})
    assert names(names_env(d, base, in_lock)) == 1


def test_names_cannot_decide_on_unreadable_toml(repo: tuple[Path, str, str]) -> None:
    d, base, _ = repo
    head = commit_with(d, base, {"pyproject.toml": "[[[ nope"})
    assert names(names_env(d, base, head)) == 2


def push_env(d: Path, base: str, patch: str, tree: str, **over: str) -> dict[str, str]:
    env = {
        "GITHUB_REPOSITORY": REPO,
        "REPAIR_DIR": str(d),
        "REPAIR_BASE": base,
        "REPAIR_PATCH_B64": patch,
        "REPAIR_TREE": tree,
        "REPAIR_BRANCH": "dependabot/uv/x-1",
        "REPAIR_ATTEMPT": "1",
    }
    env.update(over)
    return env


def tree_of(tmp_path: Path, d: Path, base: str, patch: str) -> str:
    env = {
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "REPAIR_DIR": str(d),
        "REPAIR_BASE": base,
        "REPAIR_PATCH_B64": patch,
        "REPAIR_ATTEMPT": "1",
    }
    assert build(env) == 0
    return outputs(tmp_path)["tree"]


def test_push_makes_one_signed_commit_pinned_to_the_head_it_was_built_on(
    tmp_path: Path, repo: tuple[Path, str, str]
) -> None:
    d, base, patch = repo
    tree = tree_of(tmp_path, d, base, patch)
    api = FakeApi()
    assert push(push_env(d, base, patch, tree), api) == 0
    path, payload = api.posts[0]
    assert path == "/graphql"
    inp = payload["variables"]["input"]
    assert inp["expectedHeadOid"] == base
    assert inp["branch"] == {"repositoryNameWithOwner": REPO, "branchName": "dependabot/uv/x-1"}
    assert inp["message"]["headline"].startswith("repair: ")
    additions = inp["fileChanges"]["additions"]
    assert additions == [{"path": "src/a.py", "contents": base64.b64encode(b"x = 2\n").decode()}]


def test_push_refuses_a_patch_that_is_not_the_validated_one(
    tmp_path: Path, repo: tuple[Path, str, str]
) -> None:
    d, base, patch = repo
    api = FakeApi()
    assert push(push_env(d, base, patch, "e" * 40), api) == 1
    assert api.posts == []


def test_push_fails_when_github_refuses(tmp_path: Path, repo: tuple[Path, str, str]) -> None:
    d, base, patch = repo
    tree = tree_of(tmp_path, d, base, patch)
    api = FakeApi()
    api.graphql_reply = {"errors": [{"message": "Expected branch to point to ..."}]}
    assert push(push_env(d, base, patch, tree), api) == 1
