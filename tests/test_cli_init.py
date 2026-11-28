"""Seam 1: the CLI. `init` observed through its output and the workspace it leaves behind."""

import sqlite3
from pathlib import Path

import pytest

from book_translator import main

FIXTURES = Path(__file__).parent / "fixtures" / "epub"


def init(tmp_path: Path, *extra: str, epub: str = "plain.epub") -> Path:
    workspace = tmp_path / "ws"
    main(["init", str(FIXTURES / epub), "--workspace", str(workspace), *extra])
    return workspace


def test_init_creates_a_workspace_with_a_frozen_source_and_a_database(tmp_path: Path) -> None:
    workspace = init(tmp_path, "--variety", "neutral")

    assert (workspace / "source.epub").read_bytes() == (FIXTURES / "plain.epub").read_bytes()
    assert (workspace / "book.sqlite").is_file()


def test_init_requires_a_variety(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        init(tmp_path)

    assert exc.value.code != 0
    assert "--variety" in capsys.readouterr().err
    assert not (tmp_path / "ws").exists()


def test_init_records_the_choices_in_the_database(tmp_path: Path) -> None:
    workspace = init(tmp_path, "--variety", "rioplatense")

    with sqlite3.connect(workspace / "book.sqlite") as db:
        settings = dict(db.execute("select key, value from settings"))
    assert settings["variety"] == "rioplatense"
    assert settings["target"] == "es"
    assert settings["cap_usd"] == "10.00"


def test_init_lists_the_detected_structure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path, "--variety", "neutral")

    out = capsys.readouterr().out
    assert "2 chapters" in out
    assert "One" in out and "Two" in out


def test_init_shows_a_cost_estimate_and_calls_no_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path, "--variety", "neutral")

    out = capsys.readouterr().out
    assert "Estimated cost: $" in out
    assert "cap $10.00" in out


def test_init_refuses_an_existing_workspace(tmp_path: Path) -> None:
    init(tmp_path, "--variety", "neutral")

    with pytest.raises(SystemExit) as exc:
        init(tmp_path, "--variety", "neutral")
    assert exc.value.code != 0


def test_init_rejects_a_file_that_is_not_an_epub(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"nope")

    with pytest.raises(SystemExit) as exc:
        main(["init", str(bad), "--variety", "neutral", "--workspace", str(tmp_path / "ws")])
    assert exc.value.code != 0
    assert not (tmp_path / "ws").exists()


def test_init_shows_the_estimate_for_every_stage_that_calls_the_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path, "--variety", "neutral")

    out = capsys.readouterr().out
    for stage in (
        "analysis",
        "consolidation",
        "enrichment",
        "draft",
        "tk_resolution",
        "fidelity",
        "polish",
        "post_polish_fidelity",
    ):
        assert f"  {stage}: $" in out
    assert "margin for retries" in out


def test_init_warns_when_the_cap_is_below_the_estimate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path, "--variety", "neutral", "--cap", "0.01")

    assert "Warning: the cap ($0.01) is below the estimate" in capsys.readouterr().out


def test_init_does_not_warn_when_the_cap_covers_the_estimate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path, "--variety", "neutral")

    assert "Warning" not in capsys.readouterr().out
