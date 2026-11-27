"""The validator end to end, on real repositories, and its fail-closed exits."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from repair_validate.gitdata import GitRepo
from repair_validate.run import run

PYPROJECT = """\
[project]
name = "x"
dependencies = ["httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
"""
TESTS = "def test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n"


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


def commit(directory: Path, files: dict[str, str | None]) -> str:
    for name, content in files.items():
        path = directory / name
        if content is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sh(directory, "add", "-A")
    sh(directory, "commit", "-q", "--allow-empty", "-m", "c")
    return sh(directory, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    sh(tmp_path, "init", "-q", "-b", "main")
    base = commit(
        tmp_path,
        {"pyproject.toml": PYPROJECT, "src/pkg/a.py": "x = 1\n", "tests/test_x.py": TESTS},
    )
    return tmp_path, base


def env(directory: Path, base: str, head: str) -> dict[str, str]:
    return {"REPAIR_DIR": str(directory), "REPAIR_BASE": base, "REPAIR_HEAD": head}


def test_a_source_fix_passes(repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})
    assert run(env(directory, base, head)) == 0
    assert "passed" in capsys.readouterr().out


def test_a_dependency_bump_passes(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"pyproject.toml": PYPROJECT.replace(">=0.27", ">=0.28")})
    assert run(env(directory, base, head)) == 0


def test_editing_a_test_is_rejected(
    repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    directory, base = repo
    head = commit(directory, {"tests/test_x.py": "def test_a():\n    pass\n"})
    assert run(env(directory, base, head)) == 1
    assert "tests/test_x.py" in capsys.readouterr().out


def test_weakening_pytest_config_is_rejected(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"pyproject.toml": PYPROJECT.replace('["tests"]', '["nowhere"]')})
    assert run(env(directory, base, head)) == 1


def test_a_symlink_into_src_is_rejected(repo: tuple[Path, str]) -> None:
    directory, base = repo
    (directory / "src" / "pkg" / "t.py").symlink_to("../../tests/test_x.py")
    head = commit(directory, {})
    assert run(env(directory, base, head)) == 1


def test_a_noqa_is_rejected(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "import os  # noqa\n"})
    assert run(env(directory, base, head)) == 1


def test_a_source_change_that_loses_a_test_id_is_rejected(repo: tuple[Path, str]) -> None:
    # Source may not hold tests the config collects, but if the base config collects src too,
    # a repair that deletes a collected test must still trip the ratchet.
    directory, _ = repo
    config = PYPROJECT.replace('["tests"]', '["tests", "src"]')
    base = commit(directory, {"pyproject.toml": config, "src/pkg/test_in_src.py": TESTS})
    # test files under src are refused by the allowlist; the ratchet is the second line of defence
    head = commit(directory, {"src/pkg/test_in_src.py": None})
    assert run(env(directory, base, head)) == 1


def test_empty_patch_is_rejected(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {})
    assert run(env(directory, base, head)) == 1


def test_shallow_history_fails_closed(
    repo: tuple[Path, str],
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})
    shallow = tmp_path_factory.mktemp("shallow")
    sh(shallow, "clone", "-q", "--depth", "1", f"file://{directory}", ".")
    assert run(env(shallow, base, head)) == 2
    assert "shallow" in capsys.readouterr().out


def test_head_not_descending_from_base_fails_closed(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})
    assert run(env(directory, head, base)) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"REPAIR_BASE": "main", "REPAIR_HEAD": "main"},
        {"REPAIR_BASE": "a" * 40, "REPAIR_HEAD": ""},
        {"REPAIR_BASE": "a" * 40, "REPAIR_HEAD": "b" * 40},  # not in the repository
    ],
)
def test_bad_inputs_fail_closed(repo: tuple[Path, str], bad: dict[str, str]) -> None:
    directory, _ = repo
    assert run({"REPAIR_DIR": str(directory), **bad}) == 2


def test_not_a_repository_fails_closed(tmp_path: Path) -> None:
    assert run({"REPAIR_DIR": str(tmp_path), "REPAIR_BASE": "a" * 40, "REPAIR_HEAD": "b" * 40}) == 2


def test_unreadable_patch_fails_closed(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})

    class Truncating(GitRepo):
        def patch(self, base: str, head: str) -> str:
            return super().patch(base, head)[:-5]

    assert run(env(directory, base, head), Truncating(str(directory))) == 2


def test_an_unexpected_error_fails_closed(
    repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})

    class Broken(GitRepo):
        def raw_diff(self, base: str, head: str) -> bytes:
            raise RuntimeError("boom")

    assert run(env(directory, base, head), Broken(str(directory))) == 2
    assert "RuntimeError" in capsys.readouterr().out


def test_a_syntax_error_in_tests_fails_closed(repo: tuple[Path, str]) -> None:
    directory, _ = repo
    base = commit(directory, {"tests/test_x.py": "def test_a(:\n"})
    head = commit(directory, {"src/pkg/a.py": "x = 3\n"})
    assert run(env(directory, base, head)) == 2


def test_module_entry_point_runs_from_the_scripts_dir(repo: tuple[Path, str]) -> None:
    directory, base = repo
    head = commit(directory, {"src/pkg/a.py": "x = 2\n"})
    scripts = Path(__file__).resolve().parents[1] / ".github" / "scripts"
    done = subprocess.run(
        [sys.executable, "-m", "repair_validate"],
        cwd=scripts,
        env={**os.environ, **env(directory, base, head)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
