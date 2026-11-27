"""Seam 1: the CLI. The TK gate: stop, review, approve, propagate."""

from pathlib import Path
from typing import Any

import yaml

from book_translator import main
from test_cli_bible_part2 import EPUB
from test_cli_draft import source_ids, tk
from test_cli_resolve import ResolveAdapter

REVIEW = "tk-review.yaml"


def stopped_at_gate(tmp_path: Path, adapter: ResolveAdapter, *, skip: bool = False) -> Path:
    ws = tmp_path / "ws"
    main(
        ["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"]
        + (["--skip-analysis-gate"] if skip else [])
    )
    main(["run", str(ws)], adapter=adapter)
    if not skip:
        main(["approve", str(ws)])
        main(["run", str(ws)], adapter=adapter)
    return ws


def review(ws: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((ws / REVIEW).read_text())
    return loaded


def test_run_stops_at_the_tk_gate_with_the_escalated_tks_as_cards_and_a_summary(
    tmp_path: Path,
) -> None:
    hard = tk(block=source_ids()[2], provisional="Algo.", scope="recurring", span="nothing")
    adapter = ResolveAdapter([tk(confidence=0.9), hard])

    ws = stopped_at_gate(tmp_path, adapter)

    document = review(ws)
    (card,) = document["cards"]
    assert card["id"] == "TK-2"
    assert card["type"] == "idiom"
    assert card["location"] == source_ids()[2]
    assert card["excerpt"] == hard["excerpt"]
    assert card["candidates"] == hard["candidates"]
    assert (card["confidence"], card["scope"]) == (0.4, "recurring")
    assert card["options"] == ["tarde tranquila", "noche en calma"]
    assert card["recommended"] == "tarde tranquila"
    assert (ws / "tk-review.html").is_file()
    (summary,) = document["auto_resolved"]
    assert summary["id"] == "TK-1"
    assert summary["resolution"] == "tarde tranquila"
