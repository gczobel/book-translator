"""The stage runner: advances a workspace through its stages, resumable and idempotent.

Stage state lives in the workspace database (`stages`), and each stage keeps its finished
units of work there too, so a second run does only what is left.
"""

import sqlite3
from pathlib import Path

from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import LLM, Adapter
from book_translator.stages.extract import Extraction, extraction_request
from book_translator.workspace import DB_NAME, SOURCE_NAME


def run(workspace: Path, adapter: Adapter) -> None:
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        with db:
            db.execute("create table if not exists stages (stage text primary key, status text)")
            db.execute(
                "create table if not exists extractions"
                " (chapter integer primary key, result text not null)"
            )
        _extraction(db, workspace, LLM(adapter, workspace / DB_NAME))
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
