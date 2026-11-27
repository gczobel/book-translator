"""Review gates: where the pipeline stops for the reader, and what the reader's choices change.

The analysis gate covers only the global decisions of the bible: variety, address grid, names,
glossary, motifs and the few typography choices.
"""

import sqlite3
from pathlib import Path

from book_translator.bible import Bible
from book_translator.review import Card, read_choices, record_choices, write_review
from book_translator.workspace import DB_NAME

ANALYSIS = "analysis"
THOUGHT_SETTINGS = ("italics", "plain", "quotation marks")


def review_path(workspace: Path, gate: str) -> Path:
    return workspace / f"{gate}-review.yaml"


def analysis_cards(bible: Bible, variety: str) -> list[Card]:
    cards = [
        Card(
            id="variety",
            question="Which Spanish variety should the translation use?",
            options=["peninsular", "rioplatense", "neutral"],
            recommended=variety,
            why="The variety chosen when the workspace was created.",
        ),
        Card(
            id="dialogue",
            question="How is dialogue set?",
            options=["raya-split", "inline-quotes"],
            recommended=bible.style.dialogue,
            why="The analysis found this the natural convention for the book.",
        ),
        Card(
            id="thoughts",
            question="How are characters' thoughts set?",
            options=sorted({*THOUGHT_SETTINGS, bible.style.thoughts}),
            recommended=bible.style.thoughts,
            why="The analysis found this the natural convention for the book.",
        ),
    ]
    for n, rule in enumerate(bible.address_grid, 1):
        span = f", chapters {rule.from_chapter or 1}-{rule.to_chapter or 'end'}"
        cards.append(
            Card(
                id=f"address-{n}",
                question=f"How does {rule.speaker} address {rule.addressee}?",
                context=f"{rule.speaker} to {rule.addressee}{span}",
                options=["tú", "usted"],
                recommended=rule.form,
                why="Inferred from the relationship and the register of their scenes.",
            )
        )
    return cards


def write_analysis_review(db: sqlite3.Connection, workspace: Path) -> None:
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    row = db.execute("select value from settings where key = 'variety'").fetchone()
    cards = analysis_cards(bible, str(row[0]) if row else "neutral")
    write_review(db, review_path(workspace, ANALYSIS), ANALYSIS, cards)


class GateError(Exception):
    pass


def approve_waiting_gate(workspace: Path) -> str:
    """Validate the reader's edits, record the choices and open the gate. Returns its name."""
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        has_stages = db.execute("select 1 from sqlite_master where name = 'stages'").fetchone()
        row = has_stages and db.execute("select stage from stages where status = 'waiting'").fetchone()
        if not row:
            raise GateError("no review gate is waiting")
        stage = str(row[0])
        gate = stage.removesuffix(" gate")
        choices = read_choices(db, review_path(workspace, gate), gate)
        record_choices(db, gate, choices)
        with db:
            db.execute("update stages set status = 'approved' where stage = ?", (stage,))
        return gate
    finally:
        db.close()
