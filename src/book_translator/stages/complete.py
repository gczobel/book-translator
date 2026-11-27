"""S1, after consolidation: the second half of the book bible."""

import json
import sqlite3
from typing import Self

from pydantic import model_validator

from book_translator.bible import Bible, GlossaryEntry, Part2
from book_translator.llm import LLMRequest

PROMPT_VERSION = "completion-v1"
_PROMPT = (
    "Given the first half of a book's bible and the per-chapter extractions, write the second "
    "half: the address grid (who says tú or usted to whom, directed, with chapter ranges where "
    "it changes), the glossary of recurring terms, the locked motifs, a summary of each chapter, "
    "the timeline and the predicted cruxes (puns, lyrics, quotations, dialect)."
)


def completion_request(model: str, db: sqlite3.Connection, part1: Bible) -> LLMRequest:
    extractions = [
        json.loads(r[0]) for r in db.execute("select result from extractions order by chapter")
    ]
    return LLMRequest(
        stage="completion",
        prompt_version=PROMPT_VERSION,
        model=model,
        prompt=_PROMPT,
        bible_slice=part1.model_dump_json(),
        source_text=json.dumps({"extractions": extractions}),
    )


def completion_schema(part1: Bible) -> type[Part2]:
    """The output schema, bound to this book's cast so a stray name is retried, not stored."""
    names = {m.name for m in part1.cast}

    class CastChecked(Part2):
        @model_validator(mode="after")
        def _belongs_to_the_cast(self) -> Self:
            self.check_against_cast(names)
            return self

    return CastChecked


def merged(part1: Bible, part2: Part2, db: sqlite3.Connection) -> Bible:
    """Part 1 plus the new fields, validated as a whole. Established terms stored by the
    research stage join the glossary; one the model also listed keeps the established rendering
    and origin, and the model's banned variants and context rule."""
    established = {
        str(term).casefold(): GlossaryEntry(term=term, rendering=rendering, origin="established")
        for term, rendering in db.execute(
            "select term, rendering from glossary where origin = 'established'"
        )
    }
    glossary: list[GlossaryEntry] = []
    for entry in part2.glossary:
        known = established.pop(entry.term.casefold(), None)
        if known is not None:
            entry = entry.model_copy(
                update={"term": known.term, "rendering": known.rendering, "origin": "established"}
            )
        glossary.append(entry)
    glossary.extend(established.values())
    return Bible.model_validate(
        {**part1.model_dump(), **part2.model_dump(), "glossary": [g.model_dump() for g in glossary]}
    )
