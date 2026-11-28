"""Seam 1: the CLI. `approve --choices` takes {card id: choice}; free text where a card opts in."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from test_cli_bible_part2 import EPUB, Part2Adapter, part2
from test_cli_draft import source_ids, tk
from test_cli_resolve import ResolveAdapter, tks_of
from test_cli_tk_gate import (
    EarlierRendering,
    glossary_of,
    recurring_in_chapter_two,
    stopped_at_gate,
    target_of,
    unsure,
)


def write_choices(ws: Path, choices: Any) -> Path:
    path = ws / "choices.json"
    path.write_text(json.dumps(choices, ensure_ascii=False))
    return path


def test_a_choices_file_settles_the_cards_it_names_and_leaves_the_rest(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    path = write_choices(ws, {"TK-1": "noche en calma"})

    main(["approve", str(ws), "--choices", str(path)])

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("noche en calma", "human")
    assert target_of(ws, source_ids()[1]) == "noche en calma Fin."


def test_a_choices_file_with_an_unknown_card_is_refused_and_the_tk_stays_open(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    path = write_choices(ws, {"TK-9": "x"})

    with pytest.raises(SystemExit) as exit_:
        main(["approve", str(ws), "--choices", str(path)])

    assert "TK-9" in str(exit_.value)
    (row,) = tks_of(ws)
    assert row["resolution"] is None
    with sqlite3.connect(ws / "book.sqlite") as db:
        assert db.execute("select count(*) from decisions where gate = 'tk'").fetchone() == (0,)
        assert db.execute("select status from stages where stage = 'tk gate'").fetchone() == (
            "waiting",
        )


def test_a_choices_file_that_is_not_a_json_object_is_refused(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    path = write_choices(ws, ["TK-1"])

    with pytest.raises(SystemExit) as exit_:
        main(["approve", str(ws), "--choices", str(path)])

    assert "choices.json" in str(exit_.value)
    (row,) = tks_of(ws)
    assert row["resolution"] is None


def test_free_text_on_a_tk_card_is_applied_like_a_chosen_candidate(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, EarlierRendering([recurring_in_chapter_two()]))
    path = write_choices(ws, {"TK-1": "velada plácida"})

    main(["approve", str(ws), "--choices", str(path)])

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("velada plácida", "human")
    assert target_of(ws, source_ids()[1]) == "Era una velada plácida."
    entry = next(e for e in glossary_of(ws) if e["term"] == "quiet evening")
    assert entry["rendering"] == "velada plácida"
    assert "velada plácida" not in entry["banned_variants"]
    assert {"tarde tranquila", "velada serena"} <= set(entry["banned_variants"])


def test_free_text_with_a_note_in_parentheses_is_refused_and_the_tk_stays_open(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))
    path = write_choices(ws, {"TK-1": "ustedes (plural de cortesía)"})

    with pytest.raises(SystemExit) as exit_:
        main(["approve", str(ws), "--choices", str(path)])

    assert "TK-1" in str(exit_.value)
    assert "note" in str(exit_.value)
    (row,) = tks_of(ws)
    assert row["resolution"] is None
    assert target_of(ws, source_ids()[1]) != "ustedes (plural de cortesía) Fin."
    with sqlite3.connect(ws / "book.sqlite") as db:
        assert db.execute("select count(*) from decisions where gate = 'tk'").fetchone() == (0,)
        assert db.execute("select status from stages where stage = 'tk gate'").fetchone() == (
            "waiting",
        )


def test_free_text_may_keep_a_parenthetical_the_source_excerpt_has(tmp_path: Path) -> None:
    excerpt = "It was a quiet evening (again)."
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk(excerpt=excerpt)], unsure))
    path = write_choices(ws, {"TK-1": "una velada (again)"})

    main(["approve", str(ws), "--choices", str(path)])

    (row,) = tks_of(ws)
    assert row["resolution"] == "una velada (again)"


def test_free_text_is_refused_on_a_card_that_does_not_take_it(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2())]))
    path = write_choices(ws, {"dialogue": "my own style"})

    with pytest.raises(SystemExit) as exit_:
        main(["approve", str(ws), "--choices", str(path)])

    assert "dialogue" in str(exit_.value)
    assert "raya-split" in str(exit_.value)
