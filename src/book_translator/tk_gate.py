"""The TK gate: the reader settles the TKs the resolver escalated, and the choices spread.

The gate always stops the run once TK resolution is done, even when no TK was escalated (the
review then shows only the summary of the auto-resolved ones). Approving records every card's
choice as the TK's resolution, with resolver `human`.

Propagation rules, deterministic and applied when the choices are recorded:
- The TK's provisional rendering in its own block is replaced by the chosen one.
- A recurring TK also enters the bible's glossary (origin `extracted`), the provisional
  rendering and the rejected candidates becoming banned variants; an existing entry for the term
  is updated instead of duplicated.
- Retroactive fix: in every block of an earlier chapter than the TK's, the provisional rendering
  and the rejected candidates' renderings are replaced by the chosen one, matched as whole
  words, case-sensitively, in a single pass. Later chapters are drafted with the glossary.
"""

import json
import re
import sqlite3
from pathlib import Path

from book_translator.bible import Bible, GlossaryEntry
from book_translator.epub import open_epub
from book_translator.review import Card
from book_translator.stages.resolve import replace_provisional
from book_translator.workspace import SOURCE_NAME

TK_GATE = "tk"


class TKCard(Card):
    type: str
    location: str
    excerpt: str
    candidates: list[dict[str, str]]
    confidence: float
    scope: str


class OpenTKError(Exception):
    pass


def open_tks(db: sqlite3.Connection) -> list[str]:
    return [str(r[0]) for r in db.execute("select id from tks where resolution is null")]


def require_no_open_tks(db: sqlite3.Connection) -> None:
    """Every stage after the TK gate calls this first: the book cannot proceed with an open TK."""
    if pending := open_tks(db):
        raise OpenTKError(f"open TKs must be settled first: {', '.join(pending)}")


def review_content(db: sqlite3.Connection) -> tuple[list[Card], dict[str, list[dict[str, str]]]]:
    """The escalated TKs as cards, and the summary of the auto-resolved ones."""
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("select * from tks order by rowid").fetchall()
    finally:
        db.row_factory = None
    cards: list[Card] = []
    summary: list[dict[str, str]] = []
    for row in rows:
        if row["resolution"] is not None:
            summary.append(
                {
                    "id": row["id"],
                    "location": row["block"],
                    "span": row["span"],
                    "resolution": row["resolution"],
                }
            )
            continue
        candidates = json.loads(row["candidates"])
        why = (
            "A recurring term is decided once, by you."
            if row["scope"] == "recurring"
            else "The resolver's recommendation; it was not sure enough to settle it alone."
        )
        cards.append(
            TKCard(
                id=row["id"],
                question=f"How is {row['span']!r} rendered?",
                context=row["excerpt"],
                options=[c["rendering"] for c in candidates],
                recommended=row["recommendation"],
                why=why,
                type=row["type"],
                location=row["block"],
                excerpt=row["excerpt"],
                candidates=candidates,
                confidence=row["confidence"],
                scope=row["scope"],
            )
        )
    return cards, {"auto_resolved": summary}


def apply_tk(db: sqlite3.Connection, choices: dict[str, str]) -> None:
    """Record the choices as human resolutions, update the text and the glossary."""
    workspace = Path(db.execute("pragma database_list").fetchone()[2]).parent
    chapter_of = {
        b.id: n
        for n, chapter in enumerate(open_epub(workspace / SOURCE_NAME).book().chapters)
        for scene in chapter.scenes
        for b in scene.blocks
    }
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    db.row_factory = sqlite3.Row
    try:
        rows = {
            r["id"]: r
            for r in db.execute("select * from tks where resolution is null order by rowid")
        }
    finally:
        db.row_factory = None
    with db:
        for id_, chosen in choices.items():
            row = rows.get(id_)
            if row is None:
                continue
            db.execute(
                "update tks set resolution = ?, resolver = 'human' where id = ?", (chosen, id_)
            )
            replace_provisional(db, row["block"], row["provisional"], chosen)
            if row["scope"] == "recurring":
                rejected = [
                    c["rendering"]
                    for c in json.loads(row["candidates"])
                    if c["rendering"] != chosen
                ]
                old = [row["provisional"], *rejected]
                _add_to_glossary(bible, row["span"], chosen, old, id_)
                _fix_earlier_chapters(db, chapter_of, row["block"], old, chosen)
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (bible.model_dump_json(),))


def _add_to_glossary(
    bible: Bible, term: str, rendering: str, banned: list[str], tk_id: str
) -> None:
    banned = [b for b in banned if b != rendering]
    entry = next((e for e in bible.glossary if e.term == term), None)
    if entry is None:
        bible.glossary.append(
            GlossaryEntry(
                term=term,
                rendering=rendering,
                banned_variants=banned,
                context_rule=f"Settled at the TK gate ({tk_id}).",
                origin="extracted",
            )
        )
        return
    entry.rendering = rendering
    entry.banned_variants = sorted({*entry.banned_variants, *banned})


def _fix_earlier_chapters(
    db: sqlite3.Connection,
    chapter_of: dict[str, int],
    block: str,
    old: list[str],
    chosen: str,
) -> None:
    wanted = sorted(set(old) - {chosen}, key=len, reverse=True)
    if not wanted:
        return
    pattern = re.compile("|".join(rf"(?<!\w){re.escape(o)}(?!\w)" for o in wanted))
    for source, position, text in db.execute(
        "select source, position, text from targets"
    ).fetchall():
        if chapter_of[source] < chapter_of[block]:
            fixed = pattern.sub(lambda _: chosen, text)
            if fixed != text:
                db.execute(
                    "update targets set text = ? where source = ? and position = ?",
                    (fixed, source, position),
                )
