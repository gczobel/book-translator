"""Reading commits out of a real object store, as data."""

import os
import subprocess
from pathlib import Path

import pytest

from repair_validate.diff import parse_diff
from repair_validate.errors import ValidateError
from repair_validate.gitdata import GitRepo


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
    return done.stdout.strip()


def init(directory: Path) -> None:
    sh(directory, "init", "-q", "-b", "main")


def commit(directory: Path, files: dict[str, str | None], message: str = "c") -> str:
    """Write files (None deletes), commit everything, return the commit hash."""
    for name, content in files.items():
        path = directory / name
        if content is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sh(directory, "add", "-A")
    sh(directory, "commit", "-q", "--allow-empty", "-m", message)
    return sh(directory, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init(tmp_path)
    return tmp_path


def test_diff_views_round_trip_through_the_parser(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "one\ntwo\n", "gone.txt": "x\n"})
    head = commit(repo, {"src/a.py": "one\nthree\n", "src/b.py": "new\n", "gone.txt": None})
    git = GitRepo(str(repo))
    changes = parse_diff(git.raw_diff(base, head), git.numstat(base, head), git.patch(base, head))
    assert [(c.path, c.status, c.added) for c in changes] == [
        ("gone.txt", "D", ()),
        ("src/a.py", "M", ("three",)),
        ("src/b.py", "A", ("new",)),
    ]


def test_renames_are_reported_as_delete_plus_add(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "same content here\nline two\nline three\n"})
    sh(repo, "mv", "src/a.py", "tests_a.py")
    head = commit(repo, {})
    git = GitRepo(str(repo))
    changes = parse_diff(git.raw_diff(base, head), git.numstat(base, head), git.patch(base, head))
    assert sorted((c.path, c.status) for c in changes) == [("src/a.py", "D"), ("tests_a.py", "A")]


def test_symlinks_show_up_with_their_mode(repo: Path) -> None:
    base = commit(repo, {"a": "x\n"})
    (repo / "link").symlink_to("/etc/passwd")
    head = commit(repo, {})
    git = GitRepo(str(repo))
    changes = parse_diff(git.raw_diff(base, head), git.numstat(base, head), git.patch(base, head))
    assert [(c.path, c.new_mode) for c in changes] == [("link", "120000")]


def test_hostile_content_cannot_pose_as_a_header(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "x\n"})
    head = commit(repo, {"src/a.py": "x\n+++ b/tests/evil.py\ndiff --git a/q b/q\n@@ -0,0 +1 @@\n"})
    git = GitRepo(str(repo))
    changes = parse_diff(git.raw_diff(base, head), git.numstat(base, head), git.patch(base, head))
    assert [c.path for c in changes] == ["src/a.py"]
    assert "diff --git a/q b/q" in changes[0].added


def test_gitattributes_and_diff_drivers_do_not_run(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    marker = tmp_path_factory.mktemp("marker") / "ran"
    base = commit(repo, {"src/a.py": "x\n", ".gitattributes": "*.py diff=evil\n"})
    sh(repo, "config", "diff.evil.command", f"touch {marker}")
    sh(repo, "config", "diff.evil.textconv", f"touch {marker}; cat")
    head = commit(repo, {"src/a.py": "y\n"})
    git = GitRepo(str(repo))
    git.patch(base, head)
    git.raw_diff(base, head)
    assert not marker.exists()


def test_shallow_clone_is_detected(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    commit(repo, {"a": "1\n"})
    commit(repo, {"a": "2\n"})
    shallow = tmp_path_factory.mktemp("shallow")
    sh(shallow, "clone", "-q", "--depth", "1", f"file://{repo}", ".")
    assert GitRepo(str(shallow)).is_shallow()
    assert not GitRepo(str(repo)).is_shallow()


def test_ancestry(repo: Path) -> None:
    first = commit(repo, {"a": "1\n"})
    second = commit(repo, {"a": "2\n"})
    git = GitRepo(str(repo))
    assert git.is_ancestor(first, second)
    assert not git.is_ancestor(second, first)
    with pytest.raises(ValidateError):
        git.is_ancestor("f" * 40, second)


def test_tree_lists_files_and_reads_them(repo: Path) -> None:
    sha = commit(repo, {"src/a.py": "x = 1\n", "docs/b.md": "hi\n"})
    (repo / "link").symlink_to("a")
    sha = commit(repo, {})
    tree = GitRepo(str(repo)).tree(sha)
    assert sorted(tree.paths()) == ["docs/b.md", "link", "src/a.py"]
    assert tree.read("src/a.py") == "x = 1\n"
    with pytest.raises(ValidateError):
        tree.read("link")


def test_non_utf8_blob_fails_closed(repo: Path) -> None:
    (repo / "bad.py").write_bytes(b"\xff\xfe")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "x")
    tree = GitRepo(str(repo)).tree(sh(repo, "rev-parse", "HEAD"))
    with pytest.raises(ValidateError):
        tree.read("bad.py")


@pytest.mark.parametrize("sha", ["main", "--output=/tmp/x", "abc", "G" * 40, ""])
def test_anything_but_a_full_hash_is_refused(repo: Path, sha: str) -> None:
    commit(repo, {"a": "1\n"})
    git = GitRepo(str(repo))
    with pytest.raises(ValidateError):
        git.raw_diff(sha, sha)
    with pytest.raises(ValidateError):
        git.tree(sha)
    with pytest.raises(ValidateError):
        git.require_commit(sha)


def test_unknown_object_fails_closed(repo: Path) -> None:
    head = commit(repo, {"a": "1\n"})
    git = GitRepo(str(repo))
    with pytest.raises(ValidateError):
        git.raw_diff("0" * 40, head)
    with pytest.raises(ValidateError):
        git.require_commit("0" * 40)


def test_output_over_the_limit_is_refused_not_truncated(repo: Path) -> None:
    base = commit(repo, {"a": "1\n"})
    head = commit(repo, {"a": "2\n" * 1000})
    git = GitRepo(str(repo), max_patch_bytes=100)
    with pytest.raises(ValidateError):
        git.patch(base, head)


def test_not_a_repository_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidateError):
        GitRepo(str(tmp_path)).is_shallow()
