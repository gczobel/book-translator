"""S7: after the polish, re-check each scene against the source and correct meaning drift.

The check is the S5 review (same edits, same validation) run on the polished text. A scene whose
check returns edits is corrected and checked again, at most `retries` more times. The edits of
the last check are not applied unchecked: they stay as unresolved findings for QA. A scene is
corrected in memory and written in one step, so an interrupted run redoes it from the call cache.
Corrections are recorded in `polish_edits` under this stage's name.
"""

import sqlite3

from book_translator.bible import Bible
from book_translator.config import DEFAULT_FIDELITY_RETRIES
from book_translator.epub import Epub
from book_translator.llm import LLM
from book_translator.stages.fidelity import (
    Edit,
    review_request,
    review_schema,
    scene_targets,
    scenes,
)

STAGE = "post_polish_fidelity"
PROMPT_VERSION = "post-polish-fidelity-v1"


def create_tables(db: sqlite3.Connection) -> None:
    db.execute("create table if not exists rechecked_scenes (first_block text primary key)")
    db.execute(
        "create table if not exists unresolved_findings (id integer primary key autoincrement,"
        " stage text not null, block text not null, position integer not null,"
        " old text not null, new text not null, reason text not null, category text not null)"
    )


def retries(db: sqlite3.Connection) -> int:
    row = db.execute("select value from settings where key = 'fidelity_retries'").fetchone()
    return int(row[0]) if row else DEFAULT_FIDELITY_RETRIES


def recheck(db: sqlite3.Connection, llm: LLM, source: Epub, bible: Bible, model: str) -> None:
    """Re-check every scene not yet re-checked. A scene's outcome is written in one step."""
    done = {str(r[0]) for r in db.execute("select first_block from rechecked_scenes")}
    allowed = retries(db)
    for scene in scenes(source):
        if scene.ids[0] in done:
            continue
        targets = scene_targets(db, scene)
        encoded = {i: source.encode_block(i) for i in scene.ids}
        applied: list[Edit] = []
        unresolved: list[Edit] = []
        for round_ in range(allowed + 1):
            request = review_request(STAGE, PROMPT_VERSION, model, scene, targets, bible, encoded)
            schema = review_schema(scene.ids, targets, encoded, bible)
            edits = llm.call(request, schema).output.edits
            if round_ == allowed:
                unresolved = edits
                break
            if not edits:
                break
            for edit in edits:
                text = targets[edit.block][edit.position]
                targets[edit.block][edit.position] = text.replace(edit.old, edit.new, 1)
            applied += edits
        with db:
            for edit in applied:
                text = str(
                    db.execute(
                        "select text from targets where source = ? and position = ?",
                        (edit.block, edit.position),
                    ).fetchone()[0]
                )
                db.execute(
                    "update targets set text = ? where source = ? and position = ?",
                    (text.replace(edit.old, edit.new, 1), edit.block, edit.position),
                )
                db.execute(
                    "insert into polish_edits (stage, block, position, old, new)"
                    " values (?, ?, ?, ?, ?)",
                    (STAGE, edit.block, edit.position, edit.old, edit.new),
                )
            for edit in unresolved:
                db.execute(
                    "insert into unresolved_findings"
                    " (stage, block, position, old, new, reason, category)"
                    " values (?, ?, ?, ?, ?, ?, ?)",
                    (
                        STAGE,
                        edit.block,
                        edit.position,
                        edit.old,
                        edit.new,
                        edit.reason,
                        edit.category,
                    ),
                )
            db.execute("insert into rechecked_scenes values (?)", (scene.ids[0],))
