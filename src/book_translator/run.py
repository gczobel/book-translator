"""The stage runner: advances a workspace through its stages, resumable and idempotent.

Stage state lives in the workspace database (`stages`), and each stage keeps its finished
units of work there too, so a second run does only what is left.
"""

import sqlite3
from pathlib import Path

from book_translator import (
    lexicon,  # noqa: F401  (registers the variety QA check)
    typography,
)
from book_translator.bible import Bible
from book_translator.budget import Budget
from book_translator.config import STAGE_MODELS
from book_translator.dialogue import relayout
from book_translator.epub import open_epub
from book_translator.gates import (
    ANALYSIS,
    skip_analysis_review,
    write_analysis_review,
    write_tk_review,
)
from book_translator.llm import LLM, Adapter
from book_translator.progress import Progress
from book_translator.qa import STAGE as QA_STAGE
from book_translator.qa import run_qa
from book_translator.search import Search
from book_translator.stages import draft as drafting
from book_translator.stages import fidelity as fidelity_check
from book_translator.stages import polish as polishing
from book_translator.stages import refidelity as post_polish
from book_translator.stages import resolve as resolving
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
from book_translator.tk_gate import TK_GATE
from book_translator.workspace import DB_NAME, SOURCE_NAME


def run(
    workspace: Path,
    adapter: Adapter,
    search: Search | None = None,
    progress: Progress | None = None,
) -> None:
    progress = progress or Progress(None, quiet=True)
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
            _research(db, workspace, search, progress)
        budget = Budget(workspace / DB_NAME)
        progress = progress.with_budget(budget)
        llm = LLM(adapter, workspace / DB_NAME, budget=budget)
        _extraction(db, workspace, llm, progress)
        _consolidation(db, llm, progress)
        _completion(db, llm, progress)
        _enrichment(db, llm, search, progress)
        _analysis_gate(db, workspace, progress)
        _draft(db, workspace, llm, progress)
        _tk_resolution(db, workspace, llm, progress)
        _tk_gate(db, workspace, progress)
        _fidelity(db, workspace, llm, progress)
        _polish(db, workspace, llm, progress)
        _post_polish_fidelity(db, workspace, llm, progress)
        _typography(db, workspace, progress)
        _qa(db, workspace, progress)
    finally:
        db.close()


def _begin(db: sqlite3.Connection, progress: Progress, stage: str, *, ready: bool = True) -> bool:
    """Say the stage starts and return True, unless it is not reached yet or is already done."""
    if not ready:
        return False
    if _status(db, stage) == "done":
        progress.skipped(stage)
        return False
    progress.start(stage)
    return True


def _begin_always(db: sqlite3.Connection, progress: Progress, stage: str, *, ready: bool) -> bool:
    """Like `_begin` for the deterministic stages that run again every time."""
    if ready:
        progress.start(stage)
    return ready


def _status(db: sqlite3.Connection, stage: str) -> str | None:
    row = db.execute("select status from stages where stage = ?", (stage,)).fetchone()
    return None if row is None else str(row[0])


def _set_status(db: sqlite3.Connection, stage: str, status: str) -> None:
    with db:
        db.execute("insert or replace into stages values (?, ?)", (stage, status))


def _extraction(db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "extraction"):
        return
    _set_status(db, "extraction", "running")
    source = open_epub(workspace / SOURCE_NAME)
    done = {int(r[0]) for r in db.execute("select chapter from extractions")}
    chapters = source.book().chapters
    tick = progress.unit("extraction", "chapter")
    for index, chapter in enumerate(chapters):
        if index in done:
            continue
        text = "\n".join(source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks)
        result = llm.call(extraction_request(STAGE_MODELS["analysis"], text), Extraction)
        with db:
            db.execute(
                "insert into extractions values (?, ?)", (index, result.output.model_dump_json())
            )
        tick(index + 1, len(chapters))
    _set_status(db, "extraction", "done")
    progress.end("extraction")


def _research(db: sqlite3.Connection, workspace: Path, search: Search, progress: Progress) -> None:
    if _status(db, "research") is not None:
        progress.skipped("research")
        return
    progress.start("research")
    source = open_epub(workspace / SOURCE_NAME)
    opf = next((source.read(n) for n in source.names if n.endswith(".opf")), b"")
    title = book_title(opf)
    target = db.execute("select value from settings where key = 'target'").fetchone()
    found = title is not None and research(db, search, title, str(target[0]) if target else "es")
    _set_status(db, "research", "done" if found else "nothing found")
    progress.end("research")


def _consolidation(db: sqlite3.Connection, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "consolidation"):
        return
    _set_status(db, "consolidation", "running")
    result = llm.call(consolidation_request(STAGE_MODELS["consolidation"], db), Bible)
    with db:
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (result.output.model_dump_json(),))
    _set_status(db, "consolidation", "done")
    progress.end("consolidation")


def _completion(db: sqlite3.Connection, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "completion"):
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
    progress.end("completion")


def _enrichment(
    db: sqlite3.Connection, llm: LLM, search: Search | None, progress: Progress
) -> None:
    if not _begin(db, progress, "enrichment"):
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
    progress.end("enrichment")


def _draft(db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress) -> None:
    opened = _status(db, f"{ANALYSIS} gate") in ("approved", "skipped")
    if not _begin(db, progress, "draft", ready=opened):
        return
    with db:
        drafting.create_tables(db)
    _set_status(db, "draft", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    drafting.draft(
        db,
        llm,
        open_epub(workspace / SOURCE_NAME),
        bible,
        STAGE_MODELS["draft"],
        progress.unit("draft", "passage"),
    )
    _set_status(db, "draft", "done")
    progress.end("draft")


def _tk_resolution(db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "tk_resolution", ready=_status(db, "draft") == "done"):
        return
    with db:
        resolving.create_tables(db)
    _set_status(db, "tk_resolution", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    source = open_epub(workspace / SOURCE_NAME)
    resolving.resolve(
        db, llm, source, bible, STAGE_MODELS["tk_resolution"], progress.unit("tk_resolution", "tk")
    )
    _set_status(db, "tk_resolution", "done")
    progress.end("tk_resolution")


def _fidelity(db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "fidelity", ready=_status(db, f"{TK_GATE} gate") == "approved"):
        return
    with db:
        fidelity_check.create_tables(db)
    _set_status(db, "fidelity", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    source = open_epub(workspace / SOURCE_NAME)
    fidelity_check.review(
        db, llm, source, bible, STAGE_MODELS["fidelity"], progress.unit("fidelity", "scene")
    )
    _set_status(db, "fidelity", "done")
    progress.end("fidelity")


def _polish(db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress) -> None:
    if not _begin(db, progress, "polish", ready=_status(db, "fidelity") == "done"):
        return
    with db:
        polishing.create_tables(db)
    _set_status(db, "polish", "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    source = open_epub(workspace / SOURCE_NAME)
    polishing.polish(
        db, llm, source, bible, STAGE_MODELS["polish"], progress.unit("polish", "scene")
    )
    _set_status(db, "polish", "done")
    progress.end("polish")


def _post_polish_fidelity(
    db: sqlite3.Connection, workspace: Path, llm: LLM, progress: Progress
) -> None:
    stage = post_polish.STAGE
    if not _begin(db, progress, stage, ready=_status(db, "polish") == "done"):
        return
    with db:
        post_polish.create_tables(db)
    _set_status(db, stage, "running")
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    source = open_epub(workspace / SOURCE_NAME)
    post_polish.recheck(db, llm, source, bible, STAGE_MODELS[stage], progress.unit(stage, "scene"))
    _set_status(db, stage, "done")
    progress.end(stage)


def _typography(db: sqlite3.Connection, workspace: Path, progress: Progress) -> None:
    """Deterministic and idempotent, so it runs again every time, just before QA."""
    if not _begin_always(
        db, progress, typography.STAGE, ready=_status(db, post_polish.STAGE) == "done"
    ):
        return
    with db:
        typography.create_tables(db)
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    source = open_epub(workspace / SOURCE_NAME)
    relayout(db, source, bible.style)
    typography.apply(db, source, bible)
    _set_status(db, typography.STAGE, "done")
    progress.end(typography.STAGE)


def _qa(db: sqlite3.Connection, workspace: Path, progress: Progress) -> None:
    """Deterministic, so it runs again every time: the stored targets may have changed."""
    if not _begin_always(db, progress, QA_STAGE, ready=_status(db, typography.STAGE) == "done"):
        return
    bible = Bible.model_validate_json(db.execute("select result from bible").fetchone()[0])
    found = run_qa(db, open_epub(workspace / SOURCE_NAME), bible)
    _set_status(db, QA_STAGE, "failed" if found else "done")
    progress.end(QA_STAGE)


def _tk_gate(db: sqlite3.Connection, workspace: Path, progress: Progress) -> None:
    """Always stops after TK resolution, even with nothing escalated: it cannot be skipped."""
    gate = f"{TK_GATE} gate"
    if _status(db, gate) is not None:
        progress.skipped(gate)
        return
    if _status(db, "tk_resolution") != "done":
        return
    progress.start(gate)
    write_tk_review(db, workspace)
    _set_status(db, gate, "waiting")
    progress.end(gate)


def _analysis_gate(db: sqlite3.Connection, workspace: Path, progress: Progress) -> None:
    gate = f"{ANALYSIS} gate"
    if _status(db, gate) is not None:
        progress.skipped(gate)
        return
    progress.start(gate)
    if db.execute("select 1 from settings where key = 'skip_analysis_gate'").fetchone():
        skip_analysis_review(db)
        _set_status(db, gate, "skipped")
    else:
        write_analysis_review(db, workspace)
        _set_status(db, gate, "waiting")
    progress.end(gate)
