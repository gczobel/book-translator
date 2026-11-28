"""The workspace lock: one `run` at a time."""

import os
from pathlib import Path

import pytest

from book_translator import main
from book_translator.workspace import LOCK_NAME, WorkspaceBusyError, locked
from test_cli_bible_part2 import EPUB


def test_a_lock_is_held_during_the_block_and_released_after(tmp_path: Path) -> None:
    with locked(tmp_path):
        assert (tmp_path / LOCK_NAME).read_text() == str(os.getpid())

    assert not (tmp_path / LOCK_NAME).exists()


def test_a_lock_is_released_when_the_work_fails(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), locked(tmp_path):
        raise RuntimeError("boom")

    assert not (tmp_path / LOCK_NAME).exists()


def test_a_second_holder_is_refused_while_the_first_is_alive(tmp_path: Path) -> None:
    with locked(tmp_path), pytest.raises(WorkspaceBusyError, match=str(os.getpid())):
        with locked(tmp_path):
            pass

    assert not (tmp_path / LOCK_NAME).exists()


def test_a_lock_left_by_a_process_that_is_gone_is_taken_over(tmp_path: Path) -> None:
    (tmp_path / LOCK_NAME).write_text("2147483646")  # no such process

    with locked(tmp_path):
        assert (tmp_path / LOCK_NAME).read_text() == str(os.getpid())


def test_a_lock_file_with_garbage_is_taken_over(tmp_path: Path) -> None:
    (tmp_path / LOCK_NAME).write_text("not a pid")

    with locked(tmp_path):
        pass


def test_run_stops_with_a_clear_message_while_another_run_holds_the_workspace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])

    with locked(path), pytest.raises(SystemExit) as stopped:
        main(["run", str(path)])

    assert f"another run (process {os.getpid()})" in str(stopped.value)
