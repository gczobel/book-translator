"""Seam 1: the CLI. The analysis review gate: stop, edit, approve, skip."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

from book_translator import main
from test_cli_bible_part2 import EPUB, Part2Adapter, part2

REVIEW = "analysis-review.yaml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    return path


def adapter() -> Part2Adapter:
    return Part2Adapter([json.dumps(part2())])


def cards(ws: Path) -> list[dict[str, Any]]:
    loaded = yaml.safe_load((ws / REVIEW).read_text())
    result: list[dict[str, Any]] = loaded["cards"]
    return result


def bible(ws: Path) -> dict[str, Any]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        result: dict[str, Any] = json.loads(db.execute("select result from bible").fetchone()[0])
    return result


def test_run_stops_at_the_analysis_gate_and_writes_decision_cards(ws: Path) -> None:
    main(["run", str(ws)], adapter=adapter())

    by_id = {c["id"]: c for c in cards(ws)}
    assert {"variety", "dialogue", "thoughts"} <= set(by_id)
    for card in by_id.values():
        assert {"id", "question", "context", "options", "recommended", "why", "choice"} <= set(card)
        assert card["recommended"] in card["options"]
    assert by_id["variety"]["recommended"] == "neutral"
    assert sum(c["id"].startswith("address-") for c in by_id.values()) == 3


def status(ws: Path, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    main(["status", str(ws)])
    return capsys.readouterr().out


def test_status_reports_the_waiting_gate_and_the_command_that_clears_it(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["run", str(ws)], adapter=adapter())

    out = status(ws, capsys)
    assert "analysis" in out.split("Review gate:")[1].splitlines()[0]
    assert f"Next: book-translator approve {ws}" in out


def test_approving_without_edits_accepts_every_recommendation_and_run_continues(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["run", str(ws)], adapter=adapter())
    expected = bible(ws)

    main(["approve", str(ws)])
    out = status(ws, capsys)

    assert "none waiting" in out
    with sqlite3.connect(ws / "book.sqlite") as db:
        recorded = dict(db.execute("select id, choice from decisions where gate = 'analysis'"))
    assert recorded == {c["id"]: c["recommended"] for c in cards(ws)}
    main(["run", str(ws)], adapter=adapter())  # passes the gate; nothing is asked again
    assert bible(ws) == expected
    assert "none waiting" in status(ws, capsys)


def test_approve_with_no_waiting_gate_says_so(ws: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["approve", str(ws)])
    assert "no review gate is waiting" in str(exc.value)
