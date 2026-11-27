"""S8: deterministic QA over the stored targets, before the build. No LLM is called.

A check is a function over a `QAContext` (the source blocks, the stored target blocks, the bible
and the open work left by earlier stages) returning findings, each naming a block and a message.
Checks register themselves under a name with `@check("name")`, so a later module can add its own
by importing `check` and being imported before `run_qa` runs. A QA run replaces the stored
report; any finding fails the stage, and `require_qa_clean` is what the build calls first.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock
from book_translator.workspace import DB_NAME

STAGE = "qa"


class QAFailedError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    check: str
    block: str
    message: str


@dataclass(frozen=True)
class QAContext:
    """What the checks look at. Block ids are the source blocks'; targets are in order."""

    sources: dict[str, EncodedBlock]
    targets: dict[str, list[str]]
    bible: Bible
    open_tks: list[tuple[str, str]] = field(default_factory=list)  # (TK id, block)
    unresolved: list[tuple[str, str]] = field(default_factory=list)  # (block, reason)
    length_band: tuple[float, float] = (0.5, 2.0)


_CODES = re.compile(r'<pc id="\d+">|</pc>|<ph id="\d+"/>')


def plain(text: str) -> str:
    """The text without its inline codes."""
    return _CODES.sub("", text)


def source_text(context: QAContext, block: str) -> str:
    return plain(context.sources[block].text)


def target_text(context: QAContext, block: str) -> str:
    return " ".join(plain(t) for t in context.targets.get(block, []))


def contains(text: str, phrase: str) -> bool:
    """Whole-word, case-insensitive containment."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


Check = Callable[[QAContext], list[Finding]]
CHECKS: dict[str, Check] = {}


def check(name: str) -> Callable[[Check], Check]:
    def register(function: Check) -> Check:
        CHECKS[name] = function
        return function

    return register


@check("glossary")
def glossary_renderings(context: QAContext) -> list[Finding]:
    """A source block using a glossary term must carry its rendering."""
    return [
        Finding("glossary", block, f"{entry.term!r} should be rendered {entry.rendering!r}")
        for block in context.sources
        for entry in context.bible.glossary
        if contains(source_text(context, block), entry.term)
        and not contains(target_text(context, block), entry.rendering)
    ]


@check("banned_variant")
def banned_variants(context: QAContext) -> list[Finding]:
    return [
        Finding("banned_variant", block, f"uses {variant!r}, banned for {entry.term!r}")
        for block in context.sources
        for entry in context.bible.glossary
        for variant in entry.banned_variants
        if contains(target_text(context, block), variant)
    ]


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "create table if not exists qa_findings (id integer primary key autoincrement,"
        " check_name text not null, block text not null, message text not null)"
    )


def run_checks(context: QAContext) -> list[Finding]:
    return [f for function in CHECKS.values() for f in function(context)]


def load_context(db: sqlite3.Connection, source: Epub, bible: Bible) -> QAContext:
    targets: dict[str, list[str]] = defaultdict(list)
    for block, text in db.execute("select source, text from targets order by source, position"):
        targets[str(block)].append(str(text))
    sources = {
        b.id: source.encode_block(b.id)
        for chapter in source.book().chapters
        for scene in chapter.scenes
        for b in scene.blocks
    }
    return QAContext(sources=sources, targets=dict(targets), bible=bible)


def run_qa(db: sqlite3.Connection, source: Epub, bible: Bible) -> list[Finding]:
    """Run every check and store the report, replacing the previous one."""
    found = run_checks(load_context(db, source, bible))
    with db:
        create_tables(db)
        db.execute("delete from qa_findings")
        db.executemany(
            "insert into qa_findings (check_name, block, message) values (?, ?, ?)",
            [(f.check, f.block, f.message) for f in found],
        )
    return found


def stored_findings(db: sqlite3.Connection) -> list[Finding]:
    tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}
    if "qa_findings" not in tables:
        return []
    return [
        Finding(str(c), str(b), str(m))
        for c, b, m in db.execute("select check_name, block, message from qa_findings order by id")
    ]


def render(findings: list[Finding]) -> str:
    if not findings:
        return "QA: passed"
    lines = [f"QA: {len(findings)} finding(s) block the build"]
    lines += [f"  [{f.check}] {f.block}: {f.message}" for f in findings]
    return "\n".join(lines)


def require_qa_clean(db: sqlite3.Connection) -> None:
    """The build calls this first: it cannot go ahead unless QA ran and found nothing."""
    row = db.execute("select status from stages where stage = ?", (STAGE,)).fetchone()
    if row is None or row[0] != "done" or stored_findings(db):
        raise QAFailedError("QA has not passed: run `book-translator run` and fix its findings")


def print_report(workspace: Path) -> None:
    """Print the stored QA report, if QA has run; exit with an error when it failed."""
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        has_stages = db.execute("select 1 from sqlite_master where name = 'stages'").fetchone()
        row = (
            db.execute("select status from stages where stage = ?", (STAGE,)).fetchone()
            if has_stages
            else None
        )
        found = stored_findings(db)
    finally:
        db.close()
    if row is None:
        return
    print(render(found))
    if row[0] == "failed":
        sys.exit(1)
