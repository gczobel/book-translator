"""Decision cards: the review file a reader edits at a review gate.

Generic over the gate name, so the analysis gate and the TK gate share one card format. A card
holds one decision: the question, its context, the options, the recommended answer and why. The
reader writes their answer under `choice`; an empty choice accepts the recommendation.
"""

import json
import sqlite3
from pathlib import Path

import yaml
from pydantic import BaseModel


class ReviewError(Exception):
    pass


class Card(BaseModel):
    id: str
    question: str
    context: str = ""
    options: list[str]
    recommended: str
    why: str = ""
    choice: str | None = None


def write_review(db: sqlite3.Connection, path: Path, gate: str, cards: list[Card]) -> None:
    """Write the review file and remember the cards so edits can be validated against them."""
    with db:
        db.execute(
            "create table if not exists review_cards"
            " (gate text, id text, options text, recommended text, primary key (gate, id))"
        )
        db.execute("delete from review_cards where gate = ?", (gate,))
        db.executemany(
            "insert into review_cards values (?, ?, ?, ?)",
            [(gate, c.id, json.dumps(c.options), c.recommended) for c in cards],
        )
    document = {"gate": gate, "cards": [c.model_dump() for c in cards]}
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100))


def read_choices(db: sqlite3.Connection, path: Path, gate: str) -> dict[str, str]:
    """The reader's choice for every card; an empty choice is the recommendation."""
    expected = {
        row[0]: row[1]
        for row in db.execute("select id, recommended from review_cards where gate = ?", (gate,))
    }
    edited = {c["id"]: c.get("choice") for c in yaml.safe_load(path.read_text())["cards"]}
    return {id_: str(edited.get(id_) or rec) for id_, rec in expected.items()}


def record_choices(db: sqlite3.Connection, gate: str, choices: dict[str, str]) -> None:
    with db:
        db.execute(
            "create table if not exists decisions"
            " (gate text, id text, choice text, primary key (gate, id))"
        )
        db.executemany(
            "insert or replace into decisions values (?, ?, ?)",
            [(gate, id_, choice) for id_, choice in choices.items()],
        )
