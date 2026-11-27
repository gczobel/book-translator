"""Turning the agent's patch text into a commit without touching a work tree. Seam: `patch`."""

import os
import subprocess
from pathlib import Path

import pytest

from repair.patch import PatchError, build_commit, file_changes


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


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    sh(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "keep.txt").write_text("keep\n")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path, sh(tmp_path, "rev-parse", "HEAD").strip()


def make_patch(directory: Path) -> str:
    sh(directory, "add", "-A")
    text = sh(directory, "diff", "--cached", "--no-renames", "--full-index")
    sh(directory, "reset", "-q", "--hard")
    sh(directory, "clean", "-fdq")
    return text


def test_the_patch_becomes_a_child_commit_and_the_work_tree_is_untouched(
    repo: tuple[Path, str],
) -> None:
    directory, base = repo
    (directory / "src" / "a.py").write_text("x = 1\ny = 3\n")
    (directory / "src" / "new.py").write_text("z = 1\n")
    patch = make_patch(directory)
    commit, tree = build_commit(str(directory), base, patch, "repair: test")
    assert sh(directory, "rev-parse", f"{commit}^").strip() == base
    assert sh(directory, "rev-parse", f"{commit}^{{tree}}").strip() == tree
    assert sh(directory, "show", f"{commit}:src/a.py") == "x = 1\ny = 3\n"
    assert sh(directory, "show", f"{commit}:src/new.py") == "z = 1\n"
    assert (directory / "src" / "a.py").read_text() == "x = 1\ny = 2\n"
    assert not (directory / "src" / "new.py").exists()


def test_the_same_patch_gives_the_same_tree(repo: tuple[Path, str]) -> None:
    directory, base = repo
    (directory / "src" / "a.py").write_text("x = 9\ny = 2\n")
    patch = make_patch(directory)
    assert (
        build_commit(str(directory), base, patch, "m")[1]
        == build_commit(str(directory), base, patch, "m")[1]
    )


def test_a_patch_that_does_not_apply_is_refused(repo: tuple[Path, str]) -> None:
    directory, base = repo
    bad = "diff --git a/nope b/nope\n--- a/nope\n+++ b/nope\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PatchError):
        build_commit(str(directory), base, bad, "m")


def test_a_patch_too_big_for_one_environment_variable_is_refused(
    repo: tuple[Path, str],
) -> None:
    directory, base = repo
    (directory / "src" / "a.py").write_text("y = 1\n" * 40_000)
    with pytest.raises(PatchError):
        build_commit(str(directory), base, make_patch(directory), "m")


def test_an_empty_patch_is_refused(repo: tuple[Path, str]) -> None:
    directory, base = repo
    with pytest.raises(PatchError):
        build_commit(str(directory), base, "", "m")


def test_the_file_changes_list_additions_with_content_and_deletions(
    repo: tuple[Path, str],
) -> None:
    directory, base = repo
    (directory / "src" / "a.py").write_text("x = 1\ny = 3\n")
    (directory / "keep.txt").unlink()
    (directory / "src" / "new.py").write_text("z = 1\n")
    commit, _ = build_commit(str(directory), base, make_patch(directory), "m")
    changes = file_changes(str(directory), base, commit)
    assert changes.deletions == ["keep.txt"]
    assert changes.additions == {"src/a.py": b"x = 1\ny = 3\n", "src/new.py": b"z = 1\n"}
