"""S1, last step: whole-book consolidation into the first half of the book bible."""

import json
import sqlite3

from book_translator.llm import LLMRequest

PROMPT_VERSION = "consolidate-v1"
_PROMPT = (
    "From the web research and the per-chapter extractions of a whole book, write the first half "
    "of its book bible: the profile (genre, period, setting, narrator and its distance, tense, "
    "register, how foreign the translation should feel), the style sheet (dialogue setting, "
    "thoughts, numbers, titles), the cast (names, aliases, gender, role) and a voice card for "
    "each important character (register, tics, words never used, sample lines)."
)


def consolidation_request(model: str, db: sqlite3.Connection) -> LLMRequest:
    extractions = [
        json.loads(r[0]) for r in db.execute("select result from extractions order by chapter")
    ]
    research = [
        {"term": r[0], "summary": r[1], "url": r[2]}
        for r in db.execute("select term, summary, url from research")
    ]
    return LLMRequest(
        stage="consolidation",
        prompt_version=PROMPT_VERSION,
        model=model,
        prompt=_PROMPT,
        bible_slice="",
        source_text=json.dumps({"research": research, "extractions": extractions}),
    )
