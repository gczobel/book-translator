"""The entry point: env in, pass/fail and step outputs out, never a pass by accident."""

import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lockage.pypi import PyPiClient
from lockage.run import run

# packaging 26.4 was uploaded 2026-11-23T21:44 (recorded), pytest 9.2.0 on 2026-10-27.
FIXTURES = Path(__file__).parent / "fixtures" / "pypi"
REGISTRY = '{ registry = "https://pypi.org/simple" }'


def _pkg(name: str, version: str) -> str:
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {REGISTRY}\n'


def _lock(*packages: str) -> str:
    return "version = 1\n\n" + "\n".join(packages)


def _opener(url: str) -> bytes:
    # https://pypi.org/pypi/<name>/<version>/json
    _, name, version = url.removesuffix("/json").rsplit("/", 2)
    path = FIXTURES / f"{name}-{version}.json"
    if not path.exists():
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
    return path.read_bytes()


def _env(tmp_path: Path, base: str, head: str, **over: str) -> dict[str, str]:
    (tmp_path / "base.lock").write_text(base)
    (tmp_path / "head.lock").write_text(head)
    env = {
        "BASE_LOCK": str(tmp_path / "base.lock"),
        "HEAD_LOCK": str(tmp_path / "head.lock"),
        "IS_SECURITY": "false",
        "URGENT": "false",
        "GITHUB_OUTPUT": str(tmp_path / "out"),
    }
    env.update(over)
    return env


def _outputs(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "out"
    lines = path.read_text().splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines)


def _go(env: dict[str, str], day: int) -> int:
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC) + timedelta(days=day - 1)  # 31 is 1 December
    return run(env, PyPiClient(_opener), now)


OLD = _pkg("pytest", "9.2.0")
YOUNG = _pkg("packaging", "26.4")  # uploaded 2026-11-23


def test_an_old_enough_bump_passes(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(_pkg("pytest", "9.1.0")), _lock(OLD))
    # the base's pytest 9.1.0 has no fixture, but it is not a changed entry so never looked up
    assert _go(env, 27) == 0
    assert _outputs(tmp_path) == {"passed": "true"}


def test_nothing_changed_passes_without_any_lookup(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD))
    assert run(env, PyPiClient(_boom), datetime(2026, 11, 27, tzinfo=UTC)) == 0


def _boom(url: str) -> bytes:
    raise AssertionError("no lookup expected")


def test_a_young_version_update_fails(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG))
    assert _go(env, 27) == 1  # 4 days old, needs 7
    assert _outputs(tmp_path) == {"passed": "false"}


def test_the_same_entry_passes_once_it_is_seven_days_old(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG))
    assert _go(env, 31) == 0


def test_a_security_update_needs_72_hours(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG), IS_SECURITY="true")
    assert _go(env, 25) == 1  # about 38 hours
    assert _go(env, 27) == 0  # 4 days


def test_urgent_skips_the_72_hours_for_a_security_update(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG), IS_SECURITY="true", URGENT="true")
    assert _go(env, 24) == 0  # about 14 hours old


def test_urgent_does_not_skip_the_week_for_a_version_update(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG), URGENT="true")
    assert _go(env, 25) == 1


def test_an_entry_unknown_to_pypi_fails(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, _pkg("ghost", "1.0")))
    assert _go(env, 30) == 1
    assert _outputs(tmp_path) == {"passed": "false"}


@pytest.mark.parametrize("which", ["BASE_LOCK", "HEAD_LOCK"])
def test_an_unreadable_lock_fails(tmp_path: Path, which: str) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD))
    env[which] = str(tmp_path / "missing.lock")
    assert _go(env, 30) == 1
    assert _outputs(tmp_path) == {"passed": "false"}


@pytest.mark.parametrize("which", ["BASE_LOCK", "HEAD_LOCK"])
def test_an_unparseable_lock_fails(tmp_path: Path, which: str) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD))
    Path(env[which]).write_text("[[package")
    assert _go(env, 30) == 1


@pytest.mark.parametrize("name", ["BASE_LOCK", "HEAD_LOCK", "IS_SECURITY", "URGENT"])
def test_a_missing_input_fails(tmp_path: Path, name: str) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD))
    del env[name]
    assert _go(env, 30) == 1


@pytest.mark.parametrize("value", ["", "True", "1", "yes", " true"])
def test_a_flag_other_than_true_or_false_fails(tmp_path: Path, value: str) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD), IS_SECURITY=value)
    assert _go(env, 30) == 1


def test_it_still_fails_when_the_outputs_cannot_be_written(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD), GITHUB_OUTPUT=str(tmp_path / "no" / "out"))
    assert _go(env, 30) == 1


def test_without_an_outputs_file_the_verdict_is_the_exit_code(tmp_path: Path) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD))
    del env["GITHUB_OUTPUT"]
    assert _go(env, 30) == 0


def test_the_messages_name_the_offending_entry_but_no_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _env(tmp_path, _lock(OLD), _lock(OLD, YOUNG))
    _go(env, 27)
    out = capsys.readouterr().out
    assert "packaging 26.4" in out
    assert str(tmp_path) not in out
