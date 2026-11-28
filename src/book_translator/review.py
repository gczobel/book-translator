"""Decision cards: the review file a reader edits at a review gate.

Generic over the gate name, so the analysis gate and the TK gate share one card format. A card
holds one decision: the question, its context, the options, the recommended answer and why. The
reader writes their answer under `choice`; an empty choice accepts the recommendation.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from book_translator.review_html import write_html


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
    free_text: bool = False


def write_review(
    db: sqlite3.Connection,
    path: Path,
    gate: str,
    cards: list[Card],
    extra: dict[str, Any] | None = None,
) -> None:
    """Write the review file and remember the cards so edits can be validated against them.

    `extra` adds further top-level sections to the file (read-only for the reader).
    """
    with db:
        db.execute(
            "create table if not exists review_cards"
            " (gate text, id text, options text, recommended text, primary key (gate, id))"
        )
        if "free_text" not in {r[1] for r in db.execute("pragma table_info(review_cards)")}:
            db.execute("alter table review_cards add column free_text integer not null default 0")
        db.execute("delete from review_cards where gate = ?", (gate,))
        db.executemany(
            "insert into review_cards (gate, id, options, recommended, free_text)"
            " values (?, ?, ?, ?, ?)",
            [(gate, c.id, json.dumps(c.options), c.recommended, c.free_text) for c in cards],
        )
    document = {"gate": gate, "cards": [c.model_dump() for c in cards], **(extra or {})}
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100))
    write_html(path)


def read_choices(db: sqlite3.Connection, path: Path, gate: str) -> dict[str, str]:
    """The reader's choice for every card; an empty choice is the recommendation.

    Raises ReviewError, naming the line, for malformed YAML, an unknown or repeated card id, or a
    choice that is not one of the card's options.
    """
    cards = {
        row[0]: (json.loads(row[1]), row[2])
        for row in db.execute(
            "select id, options, recommended from review_cards where gate = ?", (gate,)
        )
    }
    choices = {id_: recommended for id_, (_, recommended) in cards.items()}
    seen: set[str] = set()
    for card in _card_nodes(path):
        fields = {k.value: v for k, v in card.value if isinstance(k, yaml.ScalarNode)}
        id_node = fields.get("id")
        if not isinstance(id_node, yaml.ScalarNode) or id_node.value not in cards:
            at = id_node or card
            name = id_node.value if isinstance(id_node, yaml.ScalarNode) else "(missing)"
            raise _error(path, at, f"unknown card id {name!r}")
        id_ = id_node.value
        if id_ in seen:
            raise _error(path, id_node, f"card id {id_!r} appears twice")
        seen.add(id_)
        choice = fields.get("choice")
        if choice is None or (
            isinstance(choice, yaml.ScalarNode)
            and (choice.tag.endswith(":null") or choice.value == "")
        ):
            continue
        options = cards[id_][0]
        if not isinstance(choice, yaml.ScalarNode) or choice.value not in options:
            raise _error(path, choice, f"card {id_!r}: choice must be one of: {', '.join(options)}")
        choices[id_] = choice.value
    return choices


def read_choices_file(db: sqlite3.Connection, path: Path, gate: str) -> dict[str, str]:
    """The choices in a JSON file {card id: choice}, checked against the gate's cards.

    A choice must be one of the card's options, unless the card takes free text (then any
    non-empty text goes). Raises ReviewError for anything else.
    """
    cards = {
        row[0]: (json.loads(row[1]), bool(row[2]))
        for row in db.execute(
            "select id, options, free_text from review_cards where gate = ?", (gate,)
        )
    }
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ReviewError(f"{path.name}: cannot read the choices: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ReviewError(f"{path.name}: expected a JSON object of card id to choice")
    choices: dict[str, str] = {}
    for id_, choice in loaded.items():
        if id_ not in cards:
            raise ReviewError(f"{path.name}: unknown card id {id_!r}")
        options, free_text = cards[id_]
        if not isinstance(choice, str) or not choice.strip():
            raise ReviewError(f"{path.name}: card {id_!r}: the choice must be non-empty text")
        if choice not in options and not free_text:
            raise ReviewError(
                f"{path.name}: card {id_!r}: choice must be one of: {', '.join(options)}"
            )
        choices[id_] = choice.strip() if choice not in options else choice
    return choices


def _error(path: Path, node: yaml.Node, message: str) -> ReviewError:
    return ReviewError(f"{path.name}: line {node.start_mark.line + 1}: {message}")


def _card_nodes(path: Path) -> list[yaml.MappingNode]:
    try:
        root = yaml.compose(path.read_text())
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        raise ReviewError(f"{path.name}: {where}{getattr(exc, 'problem', None) or exc}") from exc
    cards = None
    if isinstance(root, yaml.MappingNode):
        cards = next(
            (v for k, v in root.value if isinstance(k, yaml.ScalarNode) and k.value == "cards"),
            None,
        )
    if not isinstance(cards, yaml.SequenceNode):
        raise ReviewError(f"{path.name}: line 1: expected a 'cards' list")
    for card in cards.value:
        if not isinstance(card, yaml.MappingNode):
            raise _error(path, card, "each card must be a mapping")
    return [c for c in cards.value if isinstance(c, yaml.MappingNode)]


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
