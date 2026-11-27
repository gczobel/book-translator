"""S8: deterministic QA over the stored targets, before the build. No LLM is called.

A check is a function over a `QAContext` (the source blocks, the stored target blocks, the bible
and the open work left by earlier stages) returning findings, each naming a block and a message.
Checks register themselves under a name with `@check("name")`, so a later module can add its own
by importing `check` and being imported before `run_qa` runs. A QA run replaces the stored
report; any finding fails the stage, and `require_qa_clean` is what the build calls first.
"""

import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.workspace import DB_NAME

STAGE = "qa"


DEFAULT_LENGTH_BAND = (0.5, 2.0)


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
    length_band: tuple[float, float] = DEFAULT_LENGTH_BAND
    variety: str = ""  # the workspace setting; empty when unset


_CODES = re.compile(r'<pc id="\d+">|</pc>|<ph id="\d+"/>')


def plain(text: str) -> str:
    """The text without its inline codes."""
    return _CODES.sub("", text)


def source_text(context: QAContext, block: str) -> str:
    return plain(context.sources[block].text)


def target_text(context: QAContext, block: str) -> str:
    return " ".join(plain(t) for t in context.targets.get(block, []))


def contains(text: str, phrase: str) -> bool:
    """Whole-word, case-insensitive containment (never of an empty phrase)."""
    return (
        bool(phrase)
        and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None
    )


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


MIN_RATIO_LENGTH = 20  # shorter source blocks (titles, interjections) vary too much to compare


@check("omission")
def omissions(context: QAContext) -> list[Finding]:
    return [
        Finding("omission", block, "the source has text but the target is empty")
        for block in context.sources
        if source_text(context, block).strip() and not target_text(context, block).strip()
    ]


@check("length_ratio")
def length_ratios(context: QAContext) -> list[Finding]:
    low, high = context.length_band
    found = []
    for block in context.sources:
        source, target = source_text(context, block).strip(), target_text(context, block).strip()
        if len(source) < MIN_RATIO_LENGTH or not target:  # an empty target is an omission
            continue
        ratio = len(target) / len(source)
        if not low <= ratio <= high:
            found.append(
                Finding(
                    "length_ratio",
                    block,
                    f"target is {ratio:.2f} times the source's length (band {low} to {high})",
                )
            )
    return found


_NUMBER = re.compile(r"\d+(?:[.,\u00a0 ]\d{3})*(?:[.,]\d+)?")
_NAME = re.compile(r"[A-Z][\w'-]*")
_SENTENCE_END = '.!?\u2026"\u201c\u00ab\u2014:'


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def _names(text: str) -> list[str]:
    """Capitalised words that are not merely the first word of a sentence."""
    found = []
    for match in _NAME.finditer(text):
        before = text[: match.start()].rstrip()
        if before and before[-1] not in _SENTENCE_END:
            found.append(re.sub(r"['\u2019]s$", "", match.group()))
    return found


@check("numbers")
def numbers(context: QAContext) -> list[Finding]:
    found = []
    for block in context.sources:
        target = {_digits(n) for n in _NUMBER.findall(target_text(context, block))}
        for number in _NUMBER.findall(source_text(context, block)):
            if _digits(number) not in target:
                found.append(
                    Finding("numbers", block, f"the number {number!r} is not in the target")
                )
    return found


@check("names")
def names(context: QAContext) -> list[Finding]:
    """Capitalised names of the source stay in the target, or appear as their glossary rendering."""
    rendered = {e.term: e.rendering for e in context.bible.glossary}
    found = []
    for block in context.sources:
        target = target_text(context, block)
        for name in dict.fromkeys(_names(source_text(context, block))):
            if not contains(target, name) and not contains(target, rendered.get(name, "")):
                found.append(Finding("names", block, f"the name {name!r} is not in the target"))
    return found


@check("motif")
def motifs(context: QAContext) -> list[Finding]:
    """Wherever the source uses a motif, the target carries its locked rendering, exactly."""
    return [
        Finding("motif", block, f"motif {m.name!r} must be rendered {m.locked_rendering!r}")
        for block in context.sources
        for m in context.bible.motifs
        if contains(source_text(context, block), m.name)
        and m.locked_rendering not in target_text(context, block)
    ]


@check("inline_markup")
def inline_markup(context: QAContext) -> list[Finding]:
    """Every target block keeps its source block's inline codes balanced and legal."""
    found = []
    for block, pieces in context.targets.items():
        if block not in context.sources:
            continue
        try:
            context.sources[block].validate_pieces(pieces)
        except InlineCodeError as exc:
            found.append(Finding("inline_markup", block, str(exc)))
    return found


@check("open_tk")
def open_tks(context: QAContext) -> list[Finding]:
    return [Finding("open_tk", block, f"{tk} is still open") for tk, block in context.open_tks]


@check("unresolved_finding")
def unresolved_findings(context: QAContext) -> list[Finding]:
    """Fidelity edits that S7 could not settle within its retries."""
    return [Finding("unresolved_finding", block, why) for block, why in context.unresolved]


def setting(db: sqlite3.Connection, key: str) -> str:
    row = db.execute("select value from settings where key = ?", (key,)).fetchone()
    return "" if row is None else str(row[0])


def length_band(db: sqlite3.Connection) -> tuple[float, float]:
    row = db.execute("select value from settings where key = 'qa_length_band'").fetchone()
    if row is None:
        return DEFAULT_LENGTH_BAND
    low, high = str(row[0]).split(",")
    return float(low), float(high)


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
    tks = db.execute("select id, block from tks where resolution is null order by rowid")
    unresolved = db.execute(
        "select block, category, reason, old, new from unresolved_findings order by id"
    )
    return QAContext(
        sources=sources,
        targets=dict(targets),
        bible=bible,
        open_tks=[(str(i), str(b)) for i, b in tks],
        unresolved=[(str(b), f"{c}: {r} ({o!r} -> {n!r})") for b, c, r, o, n in unresolved],
        length_band=length_band(db),
        variety=setting(db, "variety"),
    )


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
    """Print the stored QA report, if QA has run. A failed QA does not make `run` itself fail:
    the run did what it was asked, and the failed stage is what stops the build."""
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
