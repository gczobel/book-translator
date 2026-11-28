"""The TK: a spot the drafter could not settle, kept with what a reader needs to decide it."""

import json
import re
import sqlite3
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from book_translator.tolerance import choice, percentage

_TK_TYPES = Literal[
    "pun/wordplay",
    "cultural reference",
    "quote/allusion",
    "idiom",
    "ambiguity",
    "address unclear",
    "new recurring term",
    "dialect",
]
TKType = Annotated[_TK_TYPES, BeforeValidator(choice(*get_args(_TK_TYPES)))]


MAX_CANDIDATES = 3
UNSURE_CONFIDENCE = 0.2  # the most a TK claims when its recommendation could not be read
_NOISE = str.maketrans("", "", "\"'`«»“”‘’„‹›")
_NUMBER = re.compile(r"^\D{0,20}?(\d+)\D{0,3}$")


def _plain(text: str) -> str:
    return " ".join(text.translate(_NOISE).split()).casefold()


def _chosen_index(renderings: list[str], said: object) -> int | None:
    """The 0-based candidate a recommendation names: by number, exactly, or by text sans noise."""
    if isinstance(said, bool):
        return None
    if isinstance(said, int):
        return said - 1 if 1 <= said <= len(renderings) else None
    if not isinstance(said, str):
        return None
    if said in renderings:
        return renderings.index(said)
    plain = [_plain(r) for r in renderings]
    if _plain(said) and _plain(said) in plain:
        return plain.index(_plain(said))
    number = _NUMBER.match(said.strip())
    if number and 1 <= int(number.group(1)) <= len(renderings):
        return int(number.group(1)) - 1
    return None


class Candidate(BaseModel):
    rendering: str
    reason: str


class DraftedTK(BaseModel):
    """What the drafter reports about one doubtful spot of a block."""

    block: str  # id of the source block
    span: str  # the doubtful stretch of that block, as it reads in the source
    type: TKType
    excerpt: str  # the source text around the span
    provisional: str = Field(min_length=1)  # the rendering the draft carries meanwhile
    candidates: list[Candidate] = Field(min_length=2, max_length=3)
    # Asked for as the 1-based number of the chosen candidate; stored as that candidate's rendering.
    recommendation: str = Field(json_schema_extra={"type": "integer"})
    confidence: float = Field(ge=0.0, le=1.0)
    scope: Annotated[Literal["local", "recurring"], BeforeValidator(choice("local", "recurring"))]

    @model_validator(mode="before")
    @classmethod
    def _tolerate_real_output(cls, data: Any) -> Any:
        """Settle what a model gets slightly wrong, so one slip does not fail a paid passage."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        data["confidence"] = percentage(data.get("confidence"))
        candidates = data.get("candidates")
        if (
            not isinstance(candidates, list)
            or len(candidates) < 2
            or not all(
                isinstance(c, dict) and isinstance(c.get("rendering"), str) for c in candidates
            )
        ):
            return data  # not repairable: let the schema say what is wrong
        chosen = _chosen_index([c["rendering"] for c in candidates], data.get("recommendation"))
        if chosen is None:
            chosen = 0
            if isinstance(data.get("confidence"), int | float):
                data["confidence"] = min(data["confidence"], UNSURE_CONFIDENCE)
        if chosen >= MAX_CANDIDATES:  # keep the recommended one among the candidates kept
            candidates[MAX_CANDIDATES - 1], chosen = candidates[chosen], MAX_CANDIDATES - 1
        data["candidates"] = candidates[:MAX_CANDIDATES]
        data["recommendation"] = candidates[chosen]["rendering"]
        return data

    @model_validator(mode="after")
    def _recommends_a_candidate(self) -> Self:
        if self.recommendation not in {c.rendering for c in self.candidates}:
            raise ValueError("the recommendation must be one of the candidates")
        return self


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "create table if not exists tks (id text primary key, block text not null,"
        " span text not null, type text not null, excerpt text not null,"
        " provisional text not null, candidates text not null, recommendation text not null,"
        " confidence real not null, scope text not null, resolution text, resolver text)"
    )


def store(db: sqlite3.Connection, tks: list[DraftedTK]) -> None:
    """Add the TKs, open: they have no resolution and no resolver yet."""
    for tk in tks:
        number = db.execute("select count(*) from tks").fetchone()[0] + 1
        db.execute(
            "insert into tks values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null)",
            (
                f"TK-{number}",
                tk.block,
                tk.span,
                tk.type,
                tk.excerpt,
                tk.provisional,
                json.dumps([c.model_dump() for c in tk.candidates], ensure_ascii=False),
                tk.recommendation,
                tk.confidence,
                tk.scope,
            ),
        )
