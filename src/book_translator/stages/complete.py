"""S1, after consolidation: the second half of the book bible."""

import json
import sqlite3

from book_translator.bible import Bible, Part2
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


def merged(part1: Bible, part2: Part2) -> Bible:
    """Part 1 plus the new fields, validated as a whole."""
    return Bible.model_validate({**part1.model_dump(), **part2.model_dump()})
