"""S2, after the bible: real-world names against established target-language forms."""

import json
import sqlite3
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from book_translator.bible import Bible, Crux, GlossaryEntry
from book_translator.llm import LLMRequest
from book_translator.search import Search

PROMPT_VERSION = "enrich-v1"
_PROMPT = (
    "Given a book's bible and its per-chapter extractions, list the real-world places, people "
    "and works the text mentions, so that their established target-language forms can be looked up."
)


class RealName(BaseModel):
    term: str
    kind: Literal["place", "person", "work"]


class Quotation(BaseModel):
    """A quoted song, poem or passage of scripture, and what to do about its translation."""

    kind: Literal["song", "poem", "scripture"]
    location: str
    note: str = ""
    recommendation: Literal["existing", "own"]
    source: str = ""  # where the existing translation is found

    @model_validator(mode="after")
    def _an_existing_translation_names_its_source(self) -> Self:
        if self.recommendation == "existing" and not self.source:
            raise ValueError(f"an existing translation of {self.location!r} needs a source")
        return self


class Enrichment(BaseModel):
    """What the model found in the book that the real world already has a name for."""

    names: list[RealName] = []
    quotations: list[Quotation] = []


def enrichment_request(model: str, db: sqlite3.Connection, bible: Bible) -> LLMRequest:
    extractions = [
        json.loads(r[0]) for r in db.execute("select result from extractions order by chapter")
    ]
    return LLMRequest(
        stage="enrichment",
        prompt_version=PROMPT_VERSION,
        model=model,
        prompt=_PROMPT,
        bible_slice=bible.model_dump_json(),
        source_text=json.dumps({"extractions": extractions}),
    )


def look_up_names(
    db: sqlite3.Connection, search: Search, names: list[RealName], language: str
) -> None:
    """Ask the search for each name once; what it answered is kept so a rerun never asks again."""
    asked = {str(r[0]) for r in db.execute("select term from enrichment")}
    for name in names:
        if name.term in asked:
            continue
        findings = search.lookup(name.term, language, established=True)
        found = next((f for f in findings if f.rendering is not None), None)
        with db:
            db.execute(
                "insert into enrichment values (?, ?, ?)",
                (name.term, found and found.rendering, found and found.url),
            )
        asked.add(name.term)


def with_flagged_quotations(bible: Bible, quotations: list[Quotation]) -> Bible:
    """The bible with each quotation in its crux list. A crux already predicted at the same
    place gets the recommendation; otherwise a new crux is added."""
    cruxes = list(bible.cruxes)
    for q in quotations:
        recommendation: Literal["existing translation", "our own"] = (
            "existing translation" if q.recommendation == "existing" else "our own"
        )
        at = next((i for i, c in enumerate(cruxes) if c.location == q.location), None)
        if at is not None:
            cruxes[at] = cruxes[at].model_copy(
                update={"recommendation": recommendation, "source": q.source}
            )
            continue
        cruxes.append(
            Crux(
                type="lyrics" if q.kind == "song" else "quotation",
                location=q.location,
                note=f"{q.kind}: {q.note}" if q.note else q.kind,
                recommendation=recommendation,
                source=q.source,
            )
        )
    return bible.model_copy(update={"cruxes": cruxes})


def with_established_names(bible: Bible, db: sqlite3.Connection) -> Bible:
    """The bible plus a glossary entry, marked established, for each name that was found.
    A term the glossary already holds keeps its entry."""
    held = {g.term.casefold() for g in bible.glossary}
    added = [
        GlossaryEntry(term=term, rendering=rendering, origin="established", source=url)
        for term, rendering, url in db.execute(
            "select term, rendering, url from enrichment where rendering is not null"
        )
        if term.casefold() not in held
    ]
    return bible.model_copy(update={"glossary": [*bible.glossary, *added]})
