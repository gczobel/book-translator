"""S4: resolve each TK with the bible and wider context, escalating the ones only a human can.

A TK is escalated, and stays open (no resolution, no resolver), when the resolver's confidence is
below the configured threshold, when its choice carries a note in parentheses instead of plain
text, or when its scope is recurring: a term that recurs through the
book is decided once, by the human, at the TK gate. Every other TK gets the resolver's choice,
recorded with resolver `auto`, and the provisional rendering in the draft is replaced by it.
"""

import json
import re
import sqlite3
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from book_translator.bible import Bible
from book_translator.config import TK_CONFIDENCE_THRESHOLD
from book_translator.epub import Epub
from book_translator.llm import LLM, LLMRequest
from book_translator.progress import Tick, no_tick
from book_translator.stages.context import bible_slice
from book_translator.tolerance import percentage

PROMPT_VERSION = "tk-resolution-v1"
CONTEXT_BLOCKS = 8
_PROMPT = (
    "Resolve the TK: choose the rendering that fits the bible and the surrounding text best. "
    "You may pick a candidate or give a better rendering. Say how confident you are. "
    "The resolution is pasted into the sentence as is: give only the target-language text, "
    "never a note or description in parentheses; put any explanation in the reason."
)
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def has_note(rendering: str, excerpt: str) -> bool:
    """A parenthetical in the rendering that is not in the source text is a note, not text."""
    return any(p not in excerpt for p in _PARENTHETICAL.findall(rendering))


class Resolution(BaseModel):
    resolution: str = Field(min_length=1)
    confidence: Annotated[float, BeforeValidator(percentage)] = Field(ge=0.0, le=1.0)


def create_tables(db: sqlite3.Connection) -> None:
    db.execute("create table if not exists examined_tks (id text primary key)")


def resolve(
    db: sqlite3.Connection,
    llm: LLM,
    source: Epub,
    bible: Bible,
    model: str,
    progress: Tick = no_tick,
) -> None:
    """Examine every TK not yet examined. Each one's outcome is stored in a single step."""
    book = source.book()
    where = {
        b.id: (chapter, scene_ids.index(b.id), scene_ids)
        for chapter, ch in enumerate(book.chapters)
        for scene in ch.scenes
        for scene_ids in [[x.id for x in scene.blocks]]
        for b in scene.blocks
    }
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "select * from tks where id not in (select id from examined_tks) order by rowid"
        ).fetchall()
    finally:
        db.row_factory = None
    for index, row in enumerate(rows):
        progress.begin(index, len(rows))
        escalate = row["scope"] == "recurring"
        chosen: Resolution | None = None
        if not escalate:
            chapter, at, ids = where[row["block"]]
            around = ids[max(0, at - CONTEXT_BLOCKS) : at + CONTEXT_BLOCKS + 1]
            texts = [{"id": i, "text": source.encode_block(i).text} for i in around]
            card = {
                k: row[k] for k in ("id", "block", "span", "type", "excerpt", "provisional")
            } | {
                "candidates": json.loads(row["candidates"]),
                "recommendation": row["recommendation"],
                "confidence": row["confidence"],
                "scope": row["scope"],
            }
            request = LLMRequest(
                stage="tk_resolution",
                prompt_version=PROMPT_VERSION,
                model=model,
                prompt=_PROMPT,
                bible_slice=bible_slice(bible, " ".join(t["text"] for t in texts), chapter, around),
                source_text=json.dumps({"tk": card, "context": texts}),
            )
            chosen = llm.call(request, Resolution).output
            escalate = chosen.confidence < TK_CONFIDENCE_THRESHOLD or has_note(
                chosen.resolution, row["excerpt"]
            )
        with db:
            if chosen is not None and not escalate:
                db.execute(
                    "update tks set resolution = ?, resolver = 'auto' where id = ?",
                    (chosen.resolution, row["id"]),
                )
                replace_provisional(db, row["block"], row["provisional"], chosen.resolution)
            db.execute("insert into examined_tks values (?)", (row["id"],))
        progress(index + 1, len(rows))


def replace_provisional(
    db: sqlite3.Connection, block: str, provisional: str, resolution: str
) -> None:
    for position, text in db.execute(
        "select position, text from targets where source = ? order by position", (block,)
    ).fetchall():
        if provisional and provisional in text:
            db.execute(
                "update targets set text = ? where source = ? and position = ?",
                (text.replace(provisional, resolution, 1), block, position),
            )
            return
