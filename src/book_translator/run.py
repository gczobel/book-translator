"""The stage runner: advances a workspace through its stages, resumable and idempotent.

Stage state lives in the workspace database (`stages`), and each stage keeps its finished
units of work there too, so a second run does only what is left.
"""

import sqlite3
from pathlib import Path

from book_translator.bible import Bible
from book_translator.budget import Budget
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.gates import ANALYSIS, skip_analysis_review, write_analysis_review
from book_translator.llm import LLM, Adapter
from book_translator.search import Search
from book_translator.stages import draft as drafting
from book_translator.stages.complete import completion_request, completion_schema, merged
from book_translator.stages.consolidate import consolidation_request
from book_translator.stages.enrich import (
    Enrichment,
    enrichment_request,
    look_up_names,
    with_established_names,
    with_flagged_quotations,
)
from book_translator.stages.extract import Extraction, extraction_request
from book_translator.stages.research import book_title, research
from book_translator.workspace import DB_NAME, SOURCE_NAME


def run(workspace: Path, adapter: Adapter, search: Search | None = None) -> None:
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        with db:
            db.execute("create table if not exists stages (stage text primary key, status text)")
            db.execute(
                "create table if not exists extractions"
                " (chapter integer primary key, result text not null)"
            )
            db.execute(
                "create table if not exists research (term text, summary text, url text not null)"
            )
            db.execute(
                "create table if not exists glossary"
                " (term text, rendering text, origin text, source text)"
            )
            db.execute("create table if not exists bible (result text not null)")
            db.execute(
                "create table if not exists enrichment"
                " (term text primary key, rendering text, url text)"
            )
        if search is not None:
            _research(db, workspace, search)
        llm = LLM(adapter, workspace / DB_NAME, budget=Budget(workspace / DB_NAME))
        _extraction(db, workspace, llm)
        _consolidation(db, llm)
        _completion(db, llm)
        _enrichment(db, llm, search)
        _analysis_gate(db, workspace)
        _draft(db, workspace, llm)
    finally:
        db.close()


def _status(db: sqlite3.Connection, stage: str) -> str | None:
    row = db.execute("select status from stages where stage = ?", (stage,)).fetchone()
    return None if row is None else str(row[0])


def _set_status(db: sqlite3.Connection, stage: str, status: str) -> None:
    with db:
        db.execute("insert or replace into stages values (?, ?)", (stage, status))


def _extraction(db: sqlite3.Connection, workspace: Path, llm: LLM) -> None:
    if _status(db, "extraction") == "done":
        return
    _set_status(db, "extraction", "running")
    source = open_epub(workspace / SOURCE_NAME)
    done = {int(r[0]) for r in db.execute("select chapter from extractions")}
    for index, chapter in enumerate(source.book().chapters):
        if index in done:
            continue
        text = "\n".join(source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks)
        result = llm.call(extraction_request(STAGE_MODELS["analysis"], text), Extraction)
        with db:
            db.execute(
                "insert into extractions values (?, ?)", (index, result.output.model_dump_json())
            )
    _set_status(db, "extraction", "done")


def _research(db: sqlite3.Connection, workspace: Path, search: Search) -> None:
    if _status(db, "research") is not None:
        return
    source = open_epub(workspace / SOURCE_NAME)
    opf = next((source.read(n) for n in source.names if n.endswith(".opf")), b"")
    title = book_title(opf)
    target = db.execute("select value from settings where key = 'target'").fetchone()
    found = title is not None and research(db, search, title, str(target[0]) if target else "es")
    _set_status(db, "research", "done" if found else "nothing found")


def _consolidation(db: sqlite3.Connection, llm: LLM) -> None:
    if _status(db, "consolidation") == "done":
        return
    _set_status(db, "consolidation", "running")
    result = llm.call(consolidation_request(STAGE_MODELS["consolidation"], db), Bible)
    with db:
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (result.output.model_dump_json(),))
    _set_status(db, "consolidation", "done")


def _completion(db: sqlite3.Connection, llm: LLM) -> None:
    if _status(db, "completion") == "done":
        return
    _set_status(db, "completion", "running")
    part1 = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    result = llm.call(
        completion_request(STAGE_MODELS["consolidation"], db, part1), completion_schema(part1)
    )
    with db:
        db.execute("delete from bible")
        db.execute(
            "insert into bible values (?)", (merged(part1, result.output, db).model_dump_json(),)
        )
    _set_status(db, "completion", "done")


def _enrichment(db: sqlite3.Connection, llm: LLM, search: Search | None) -> None:
    if _status(db, "enrichment") == "done":
        return
    _set_status(db, "enrichment", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    found = llm.call(enrichment_request(STAGE_MODELS["enrichment"], db, bible), Enrichment).output
    target = db.execute("select value from settings where key = 'target'").fetchone()
    evaluation = db.execute("select value from settings where key = 'evaluation'").fetchone()
    if search is not None and evaluation is None:  # ADR 0004: no lookups in evaluation mode
        look_up_names(db, search, found.names, str(target[0]) if target else "es")
    enriched = with_flagged_quotations(with_established_names(bible, db), found.quotations)
    with db:
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (enriched.model_dump_json(),))
    _set_status(db, "enrichment", "done")


def _draft(db: sqlite3.Connection, workspace: Path, llm: LLM) -> None:
    opened = _status(db, f"{ANALYSIS} gate") in ("approved", "skipped")
    if not opened or _status(db, "draft") == "done":
        return
    with db:
        drafting.create_tables(db)
    _set_status(db, "draft", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    drafting.draft(db, llm, open_epub(workspace / SOURCE_NAME), bible, STAGE_MODELS["draft"])
    _set_status(db, "draft", "done")


def _analysis_gate(db: sqlite3.Connection, workspace: Path) -> None:
    gate = f"{ANALYSIS} gate"
    if _status(db, gate) is not None:
        return
    if db.execute("select 1 from settings where key = 'skip_analysis_gate'").fetchone():
        skip_analysis_review(db)
        _set_status(db, gate, "skipped")
        return
    write_analysis_review(db, workspace)
    _set_status(db, gate, "waiting")
