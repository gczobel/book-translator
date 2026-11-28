"""Review gates: where the pipeline stops for the reader, and what the reader's choices change.

The analysis gate covers only the global decisions of the bible: variety, address grid, names,
glossary, motifs and the few typography choices.
"""

import sqlite3
from pathlib import Path

from book_translator.bible import Bible
from book_translator.review import (
    Card,
    read_choices,
    read_choices_file,
    record_choices,
    write_review,
)
from book_translator.review_html import write_html
from book_translator.tk_gate import TK_GATE, apply_tk, review_content
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
    for n, entry in enumerate(bible.glossary, 1):
        names = entry.origin == "established"
        cards.append(
            Card(
                id=f"{'name' if names else 'glossary'}-{n}",
                question=f"How is {entry.term!r} rendered?",
                context=entry.source or entry.context_rule,
                options=[entry.rendering, entry.term]
                if entry.rendering != entry.term
                else [entry.rendering],
                recommended=entry.rendering,
                free_text=True,
                why=(
                    "The usual Spanish form, found in a source."
                    if names
                    else "The analysis settled on this; the other option keeps the original."
                ),
            )
        )
    for n, motif in enumerate(bible.motifs, 1):
        cards.append(
            Card(
                id=f"motif-{n}",
                question=f"How is the motif {motif.name!r} rendered wherever it recurs?",
                context=motif.description,
                options=sorted({motif.locked_rendering, motif.name}),
                recommended=motif.locked_rendering,
                free_text=True,
                why="Locked so that the motif reads the same each time it returns.",
            )
        )
    return cards


def _stored_analysis_cards(db: sqlite3.Connection) -> list[Card]:
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    row = db.execute("select value from settings where key = 'variety'").fetchone()
    return analysis_cards(bible, str(row[0]) if row else "neutral")


def write_analysis_review(db: sqlite3.Connection, workspace: Path) -> None:
    cards = _stored_analysis_cards(db)
    write_review(db, review_path(workspace, ANALYSIS), ANALYSIS, cards)


def skip_analysis_review(db: sqlite3.Connection) -> None:
    """Unattended run: take every recommendation without writing a review file."""
    choices = {c.id: c.recommended for c in _stored_analysis_cards(db)}
    record_choices(db, ANALYSIS, choices)
    apply_analysis(db, choices)


def apply_analysis(db: sqlite3.Connection, choices: dict[str, str]) -> None:
    """Make the recorded choices the bible's and the workspace's own, for later stages."""
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    style = bible.style
    style.dialogue = choices.get("dialogue", style.dialogue)  # type: ignore[assignment]
    style.thoughts = choices.get("thoughts", style.thoughts)
    for n, rule in enumerate(bible.address_grid, 1):
        rule.form = choices.get(f"address-{n}", rule.form)  # type: ignore[assignment]
    for n, entry in enumerate(bible.glossary, 1):
        prefix = "name" if entry.origin == "established" else "glossary"
        entry.rendering = choices.get(f"{prefix}-{n}", entry.rendering)
    for n, motif in enumerate(bible.motifs, 1):
        motif.locked_rendering = choices.get(f"motif-{n}", motif.locked_rendering)
    with db:
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (bible.model_dump_json(),))
        if "variety" in choices:
            db.execute(
                "insert or replace into settings values ('variety', ?)", (choices["variety"],)
            )


class GateError(Exception):
    pass


def approve_waiting_gate(workspace: Path, choices_file: Path | None = None) -> str:
    """Validate the reader's edits, record the choices and open the gate. Returns its name.

    A choices file {card id: choice} overrides the review file's choices for the cards it names.
    """
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        has_stages = db.execute("select 1 from sqlite_master where name = 'stages'").fetchone()
        row = (
            has_stages
            and db.execute("select stage from stages where status = 'waiting'").fetchone()
        )
        if not row:
            raise GateError("no review gate is waiting")
        stage = str(row[0])
        gate = stage.removesuffix(" gate")
        choices = read_choices(db, review_path(workspace, gate), gate)
        if choices_file is not None:
            choices.update(read_choices_file(db, choices_file, gate))
        write_html(review_path(workspace, gate))
        record_choices(db, gate, choices)
        APPLIERS[gate](db, choices)
        with db:
            db.execute("update stages set status = 'approved' where stage = ?", (stage,))
        return gate
    finally:
        db.close()


def write_tk_review(db: sqlite3.Connection, workspace: Path) -> None:
    cards, extra = review_content(db)
    write_review(db, review_path(workspace, TK_GATE), TK_GATE, cards, extra)


APPLIERS = {ANALYSIS: apply_analysis, TK_GATE: apply_tk}
