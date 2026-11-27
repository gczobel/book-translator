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


def edit(ws: Path, old: str, new: str) -> None:
    path = ws / REVIEW
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def decisions(ws: Path) -> list[Any]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        try:
            return db.execute("select * from decisions").fetchall()
        except sqlite3.OperationalError:
            return []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("choice: null", "choice: maybe", "line"),
        ("- id: variety", "- id: nonsense", "nonsense"),
        ("recommended: neutral", "recommended: neutral: x", "line"),
    ],
)
def test_an_invalid_edit_is_rejected_with_its_line_and_nothing_is_recorded(
    ws: Path, old: str, new: str, message: str
) -> None:
    main(["run", str(ws)], adapter=adapter())
    edit(ws, old, new)
    line = next(
        i for i, text in enumerate((ws / REVIEW).read_text().splitlines(), 1) if new in text
    )

    with pytest.raises(SystemExit) as exc:
        main(["approve", str(ws)])

    assert f"line {line}" in str(exc.value)
    assert message in str(exc.value)
    assert decisions(ws) == []


def test_a_choice_outside_the_options_names_the_card_and_the_options(ws: Path) -> None:
    main(["run", str(ws)], adapter=adapter())
    edit(ws, "choice: null", "choice: martian")

    with pytest.raises(SystemExit) as exc:
        main(["approve", str(ws)])

    assert "variety" in str(exc.value)
    assert "neutral" in str(exc.value)


def choose(ws: Path, card_id: str, answer: str) -> None:
    text = (ws / REVIEW).read_text()
    marker = f"- id: {card_id}\n"
    start = text.index(marker)
    end = text.index("choice: null", start)
    (ws / REVIEW).write_text(text[:end] + f"choice: {answer}" + text[end + len("choice: null") :])


def test_recorded_choices_are_applied_to_the_bible_and_the_settings(ws: Path) -> None:
    main(["run", str(ws)], adapter=adapter())
    choose(ws, "address-1", "tú")
    choose(ws, "dialogue", "inline-quotes")
    choose(ws, "thoughts", "plain")
    choose(ws, "variety", "rioplatense")

    main(["approve", str(ws)])

    grid = bible(ws)["address_grid"]
    assert [r["form"] for r in grid] == ["tú", "tú", "usted"]
    assert bible(ws)["style"]["dialogue"] == "inline-quotes"
    assert bible(ws)["style"]["thoughts"] == "plain"
    with sqlite3.connect(ws / "book.sqlite") as db:
        assert db.execute("select value from settings where key = 'variety'").fetchone() == (
            "rioplatense",
        )


GLOSSARY = [
    {"term": "ghost", "rendering": "fantasma", "origin": "extracted"},
    {"term": "London", "rendering": "Londres", "origin": "established", "source": "https://e.org"},
]
MOTIFS = [{"name": "the stain", "locked_rendering": "la mancha"}]


def test_names_glossary_and_motifs_each_get_a_card_whose_choice_is_applied(ws: Path) -> None:
    extra = part2(glossary=GLOSSARY, motifs=MOTIFS)
    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(extra)]))

    ids = {c["id"]: c for c in cards(ws)}
    assert any(i.startswith("name-") for i in ids)
    assert any(i.startswith("glossary-") for i in ids)
    assert any(i.startswith("motif-") for i in ids)
    glossary_id = next(i for i in ids if i.startswith("glossary-"))
    motif_id = next(i for i in ids if i.startswith("motif-"))
    assert ids[glossary_id]["recommended"] == "fantasma"
    choose(ws, glossary_id, "ghost")
    choose(ws, motif_id, "the stain")

    main(["approve", str(ws)])

    assert {g["term"]: g["rendering"] for g in bible(ws)["glossary"]}["ghost"] == "ghost"
    assert bible(ws)["motifs"][0]["locked_rendering"] == "the stain"


def test_the_skip_setting_passes_the_gate_unattended(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "skipped"
    main(
        ["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"]
        + ["--skip-analysis-gate"]
    )

    main(["run", str(path)], adapter=adapter())

    assert "none waiting" in status(path, capsys)
    assert not (path / REVIEW).exists()
    assert [r["form"] for r in bible(path)["address_grid"]] == ["usted", "tú", "usted"]


def test_approve_with_no_waiting_gate_says_so(ws: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["approve", str(ws)])
    assert "no review gate is waiting" in str(exc.value)
