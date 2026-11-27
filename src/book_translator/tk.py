"""The TK: a spot the drafter could not settle, kept with what a reader needs to decide it."""

import json
import sqlite3
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

TKType = Literal[
    "pun/wordplay",
    "cultural reference",
    "quote/allusion",
    "idiom",
    "ambiguity",
    "address unclear",
    "new recurring term",
    "dialect",
]


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
    recommendation: str  # one of the candidates' renderings
    confidence: float = Field(ge=0.0, le=1.0)
    scope: Literal["local", "recurring"]

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
