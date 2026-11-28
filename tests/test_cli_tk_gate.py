"""Seam 1: the CLI. The TK gate: stop, review, approve, propagate."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

from book_translator import main
from book_translator.llm import LLMRequest
from book_translator.tk_gate import OpenTKError, require_no_open_tks
from test_cli_bible_part2 import EPUB
from test_cli_draft import source_ids, tk
from test_cli_resolve import ResolveAdapter, tks_of

REVIEW = "tk-review.yaml"


def unsure(card: dict[str, Any]) -> dict[str, Any]:
    return {"resolution": card["recommendation"], "confidence": 0.1}


def sure_of_the_second(card: dict[str, Any]) -> dict[str, Any]:
    return {**unsure(card), "confidence": 0.1 if card["id"] == "TK-1" else 0.9}


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


def test_the_gate_stops_even_when_the_analysis_gate_was_skipped_and_nothing_was_escalated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk(confidence=0.9)]), skip=True)

    document = review(ws)
    assert document["cards"] == []
    assert [s["id"] for s in document["auto_resolved"]] == ["TK-1"]
    capsys.readouterr()
    main(["status", str(ws)])
    out = capsys.readouterr().out
    assert "Review gate: tk is waiting" in out
    assert f"Next: book-translator approve {ws}" in out


def test_the_html_view_shows_the_tk_details(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk(excerpt="It was a quiet evening.")], unsure))

    page = (ws / "tk-review.html").read_text()

    assert "It was a quiet evening." in page
    assert "more literary" in page


def edit_choice(ws: Path, card_id: str, choice: str) -> None:
    document = review(ws)
    next(c for c in document["cards"] if c["id"] == card_id)["choice"] = choice
    (ws / REVIEW).write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False))


def target_of(ws: Path, block: str) -> str:
    with sqlite3.connect(ws / "book.sqlite") as db:
        rows = db.execute(
            "select text from targets where source = ? order by position", (block,)
        ).fetchall()
    return "\n".join(r[0] for r in rows)


def test_approving_records_the_readers_choices_as_human_resolutions_and_updates_the_text(
    tmp_path: Path,
) -> None:
    easy = tk(block=source_ids()[2], provisional="Algo.", confidence=0.9)
    ws = stopped_at_gate(
        tmp_path,
        ResolveAdapter(
            [tk(), easy], lambda c: {**unsure(c), "confidence": 0.1 if c["id"] == "TK-1" else 0.9}
        ),
    )
    edit_choice(ws, "TK-1", "noche en calma")

    main(["approve", str(ws)])

    first, second = tks_of(ws)
    assert (first["resolution"], first["resolver"]) == ("noche en calma", "human")
    assert second["resolver"] == "auto"
    assert target_of(ws, source_ids()[1]) == "noche en calma Fin."


def test_approving_without_edits_takes_the_recommendation(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))

    main(["approve", str(ws)])

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("tarde tranquila", "human")


def test_a_choice_that_is_not_a_candidate_is_refused_and_the_tk_stays_open(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    edit_choice(ws, "TK-1", "algo inventado")

    with pytest.raises(SystemExit):
        main(["approve", str(ws)])

    (row,) = tks_of(ws)
    assert row["resolution"] is None


def recurring_in_chapter_two() -> dict[str, Any]:
    return tk(
        block=source_ids()[6],
        span="quiet evening",
        type="new recurring term",
        scope="recurring",
        provisional="Fin.",
        candidates=[
            {"rendering": "tarde tranquila", "reason": "plain"},
            {"rendering": "velada serena", "reason": "literary"},
        ],
        recommendation="tarde tranquila",
    )


def glossary_of(ws: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        bible = json.loads(db.execute("select result from bible").fetchone()[0])
    glossary: list[dict[str, Any]] = bible["glossary"]
    return glossary


class EarlierRendering(ResolveAdapter):
    """Chapter one was drafted with a rendering of the term, before it was flagged."""

    def _draft(self, request: LLMRequest, attempt: int) -> str:
        draft = json.loads(super()._draft(request, attempt))
        for block in draft["blocks"]:
            if block["source"] == source_ids()[1]:
                block["targets"] = ["Era una tarde tranquila."]
        return json.dumps(draft)


def test_a_resolved_recurring_tk_joins_the_glossary_and_earlier_chapters_follow(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, EarlierRendering([recurring_in_chapter_two()]))
    edit_choice(ws, "TK-1", "velada serena")

    main(["approve", str(ws)])

    assert target_of(ws, source_ids()[1]) == "Era una velada serena."
    entry = next(e for e in glossary_of(ws) if e["term"] == "quiet evening")
    assert entry["rendering"] == "velada serena"
    assert "tarde tranquila" in entry["banned_variants"]


def test_a_local_tk_does_not_touch_the_glossary(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    before = glossary_of(ws)

    main(["approve", str(ws)])

    assert glossary_of(ws) == before


def test_the_open_tk_check_refuses_while_any_tk_is_open(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    with sqlite3.connect(ws / "book.sqlite") as db:
        with pytest.raises(OpenTKError, match="TK-1"):
            require_no_open_tks(db)
    main(["approve", str(ws)])
    with sqlite3.connect(ws / "book.sqlite") as db:
        require_no_open_tks(db)


def test_a_candidate_that_is_a_note_in_parentheses_is_flagged_on_the_card(
    tmp_path: Path,
) -> None:
    noted = {"rendering": "ustedes (plural de cortesía/neutro)", "reason": "a description"}
    candidates = [{"rendering": "ustedes", "reason": "plain"}, noted]
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk(candidates=candidates)], unsure))

    (card,) = review(ws)["cards"]

    assert "ustedes (plural de cortesía/neutro)" in card["why"]
    assert "note" in card["why"]


def test_an_empty_string_choice_accepts_the_recommendation_like_a_missing_one(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    edit_choice(ws, "TK-1", "")

    main(["approve", str(ws)])

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("tarde tranquila", "human")
