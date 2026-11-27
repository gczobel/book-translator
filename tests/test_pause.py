"""The pause switch: only an explicit `false` lets automation run."""

from pathlib import Path

import pytest

from pause.core import decide
from pause.run import run


@pytest.mark.parametrize(
    "value,state",
    [
        ("false", "run"),
        ("true", "paused"),
        # anything else, or nothing, is "can't read it": stop and tell the owner
        (None, "unreadable"),
        ("", "unreadable"),
        (" false", "unreadable"),
        ("false ", "unreadable"),
        ("False", "unreadable"),
        ("TRUE", "unreadable"),
        ("0", "unreadable"),
        ("no", "unreadable"),
        ("false\n", "unreadable"),
        ("maybe", "unreadable"),
    ],
)
def test_decide(value: str | None, state: str) -> None:
    assert decide(value).state == state


def test_only_run_lets_automation_proceed() -> None:
    assert decide("false").paused is False
    assert decide("true").paused is True
    assert decide(None).paused is True


def _read(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def test_run_writes_the_outputs(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run({"PAUSE_VALUE": "false", "GITHUB_OUTPUT": str(out)}) == 0
    assert _read(out) == {"state": "run", "paused": "false"}


def test_a_deliberate_pause_is_not_an_error(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run({"PAUSE_VALUE": "true", "GITHUB_OUTPUT": str(out)}) == 0
    assert _read(out) == {"state": "paused", "paused": "true"}


def test_an_unreadable_variable_pauses_and_says_so(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run({"GITHUB_OUTPUT": str(out)}) == 0  # the escalation job acts on the state
    assert _read(out) == {"state": "unreadable", "paused": "true"}


def test_no_output_file_fails_the_step_so_callers_stay_paused() -> None:
    assert run({"PAUSE_VALUE": "false"}) != 0
    assert run({"PAUSE_VALUE": "false", "GITHUB_OUTPUT": "/nonexistent-dir/out"}) != 0
