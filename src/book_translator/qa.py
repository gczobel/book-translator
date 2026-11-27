"""S8: deterministic QA over the stored targets, before the build. No LLM is called.

A check is a function over a `QAContext` (the source blocks, the stored target blocks, the bible
and the open work left by earlier stages) returning findings, each naming a block and a message.
Checks register themselves under a name with `@check("name")`, so a later module can add its own
by importing `check` and being imported before `run_qa` runs. A QA run replaces the stored
report; any finding fails the stage, and `require_qa_clean` is what the build calls first.
"""

import hashlib
import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.tolerance import plain as fold
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


_ARTICLE = re.compile(r"^(?:el|la|los|las)\s+", re.IGNORECASE)
_NOTE = re.compile(r"\s*\([^)]*\)")


def renderings(rendering: str) -> list[str]:
    """The wordings a bible rendering allows: `a / b` is either one, a note in brackets is not
    part of the wording, and a leading article may change or go (`el X` in `al X`, `del X`)."""
    found = []
    for alternative in rendering.split(" / "):
        wording = _NOTE.sub("", alternative).strip()
        if not wording:
            continue
        found.append(wording)
        bare = _ARTICLE.sub("", wording)
        if bare != wording and bare:
            found.append(bare)
    return found


def rendered(text: str, rendering: str) -> bool:
    """Whether `text` carries `rendering`, in any of the wordings it allows."""
    return any(contains(text, wording) for wording in renderings(rendering))


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
        and not rendered(target_text(context, block), entry.rendering)
    ]


@check("banned_variant")
def banned_variants(context: QAContext) -> list[Finding]:
    return [
        Finding("banned_variant", block, f"uses {variant!r}, banned for {entry.term!r}")
        for block in context.sources
        for entry in context.bible.glossary
        for variant in entry.banned_variants
        if contains(source_text(context, block), entry.term)
        and contains(target_text(context, block), variant)
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


_HONORIFIC_DOT = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Rev|Hon|St)\.$")


def _names(text: str) -> list[str]:
    """Capitalised words that are not merely the first word of a sentence."""
    found = []
    for match in _NAME.finditer(text):
        before = text[: match.start()].rstrip()
        if before and (before[-1] not in _SENTENCE_END or _HONORIFIC_DOT.search(before)):
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


_HONORIFICS = {"Mr", "Mrs", "Miss", "Ms", "Sir", "Lord", "Lady", "Dr", "Rev", "Hon", "Messrs"}
_TITLES = {  # ranks and roles that have a Spanish word of their own
    "Duke",
    "Duchess",
    "Dowager",
    "Earl",
    "Count",
    "Baron",
    "Prince",
    "Princess",
    "King",
    "Queen",
    "Ghost",
    "Minister",
    "Colonel",
    "Captain",
    "General",
    "Reverend",
    "Bishop",
    "Doctor",
}
_ARTICLE_START = re.compile(r"^(?:the|a|an)\s", re.IGNORECASE)


def _cast_names(context: QAContext) -> set[str]:
    """The capitalised words of the cast's names and aliases that stay as they are: not those of a
    description (`the American Minister`), an honorific or a single letter."""
    found = set()
    for member in context.bible.cast:
        for label in (member.name, *member.aliases):
            if _ARTICLE_START.match(label):
                continue
            found |= {
                w for w in _NAME.findall(label) if len(w) > 1 and w not in _HONORIFICS | _TITLES
            }
    return found


def _in_target(target: str, name: str) -> bool:
    """The name is there, whatever its accents, case or a plural s."""
    folded = fold(target)
    return any(contains(folded, form) for form in {fold(name), fold(name).removesuffix("s")})


@check("names")
def names(context: QAContext) -> list[Finding]:
    """A character's name in the source stays in the target, or appears as its glossary rendering.
    Other capitalised words (places, titles, nationalities) have Spanish forms of their own and
    are the glossary check's business."""
    rendering = {e.term: e.rendering for e in context.bible.glossary}
    cast = _cast_names(context)
    found = []
    for block in context.sources:
        target = target_text(context, block)
        for name in dict.fromkeys(_names(source_text(context, block))):
            if name in cast and not _in_target(target, name):
                if not rendered(target, rendering.get(name, "")):
                    found.append(Finding("names", block, f"the name {name!r} is not in the target"))
    return found


def _carries_exactly(text: str, rendering: str) -> bool:
    """A wording of the rendering is there, whole words, with its own spelling (a capital to open
    a sentence is the one thing that may differ)."""
    return any(
        re.search(rf"(?<!\w){re.escape(w[:1].upper() + w[1:])}(?!\w)", text) is not None
        or re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) is not None
        for w in renderings(rendering)
    )


@check("motif")
def motifs(context: QAContext) -> list[Finding]:
    """Wherever the source uses a motif, the target carries its locked rendering, exactly."""
    return [
        Finding("motif", block, f"motif {m.name!r} must be rendered {m.locked_rendering!r}")
        for block in context.sources
        for m in context.bible.motifs
        if contains(source_text(context, block), m.name)
        and not _carries_exactly(target_text(context, block), m.locked_rendering)
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
    db.execute(
        "create table if not exists qa_accepted (id integer primary key autoincrement,"
        " check_name text not null, block text not null, message text not null,"
        " reason text not null default '')"
    )
    db.execute(
        "create table if not exists qa_waivers (check_name text not null, block text not null,"
        " target_hash text not null, reason text not null default '',"
        " primary key (check_name, block))"
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


class WaiverError(Exception):
    """A finding cannot be waived (there is no such open finding)."""


def target_hash(texts: list[str]) -> str:
    """What a waiver was given for: the block's target text as it was when it was looked at."""
    return hashlib.sha256(" ".join(plain(t) for t in texts).encode()).hexdigest()


def run_qa(db: sqlite3.Connection, source: Epub, bible: Bible) -> list[Finding]:
    """Run every check and store the report, replacing the previous one. The findings returned
    are the open ones: a finding the owner waived, for a block whose text has not changed since,
    is kept apart as accepted."""
    context = load_context(db, source, bible)
    found = run_checks(context)
    with db:
        create_tables(db)
        waived = {
            (str(c), str(b)): (str(h), str(r))
            for c, b, h, r in db.execute(
                "select check_name, block, target_hash, reason from qa_waivers"
            )
        }
        open_, accepted = [], []
        for f in found:
            waiver = waived.get((f.check, f.block))
            if waiver and waiver[0] == target_hash(context.targets.get(f.block, [])):
                accepted.append((f, waiver[1]))
            else:
                open_.append(f)
        db.execute("delete from qa_findings")
        db.execute("delete from qa_accepted")
        db.executemany(
            "insert into qa_findings (check_name, block, message) values (?, ?, ?)",
            [(f.check, f.block, f.message) for f in open_],
        )
        db.executemany(
            "insert into qa_accepted (check_name, block, message, reason) values (?, ?, ?, ?)",
            [(f.check, f.block, f.message, why) for f, why in accepted],
        )
    return open_


def waive(db: sqlite3.Connection, check_name: str, blocks: list[str], reason: str = "") -> int:
    """Accept the open `check_name` findings of `blocks`, as they stand now. Returns how many
    findings that accepted. A block with no such open finding is an error and changes nothing."""
    create_tables(db)
    missing = [
        b
        for b in blocks
        if not db.execute(
            "select 1 from qa_findings where check_name = ? and block = ?", (check_name, b)
        ).fetchone()
    ]
    if missing:
        raise WaiverError(f"no open {check_name} finding in block(s): {', '.join(missing)}")
    count = 0
    with db:
        for block in blocks:
            texts = [
                str(r[0])
                for r in db.execute(
                    "select text from targets where source = ? order by position", (block,)
                )
            ]
            db.execute(
                "insert or replace into qa_waivers values (?, ?, ?, ?)",
                (check_name, block, target_hash(texts), reason),
            )
            rows = db.execute(
                "select check_name, block, message from qa_findings"
                " where check_name = ? and block = ?",
                (check_name, block),
            ).fetchall()
            db.executemany(
                "insert into qa_accepted (check_name, block, message, reason) values (?, ?, ?, ?)",
                [(*row, reason) for row in rows],
            )
            db.execute(
                "delete from qa_findings where check_name = ? and block = ?", (check_name, block)
            )
            count += len(rows)
        if not db.execute("select 1 from qa_findings").fetchone():
            db.execute("update stages set status = 'done' where stage = ?", (STAGE,))
    return count


def stored_accepted(db: sqlite3.Connection) -> list[tuple[Finding, str]]:
    tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}
    if "qa_accepted" not in tables:
        return []
    return [
        (Finding(str(c), str(b), str(m)), str(r))
        for c, b, m, r in db.execute(
            "select check_name, block, message, reason from qa_accepted order by id"
        )
    ]


def stored_findings(db: sqlite3.Connection) -> list[Finding]:
    tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}
    if "qa_findings" not in tables:
        return []
    return [
        Finding(str(c), str(b), str(m))
        for c, b, m in db.execute("select check_name, block, message from qa_findings order by id")
    ]


def render(findings: list[Finding], accepted: list[tuple[Finding, str]] | None = None) -> str:
    accepted = accepted or []
    note = f" ({len(accepted)} accepted)" if accepted else ""
    lines = [
        "QA: passed" + note
        if not findings
        else f"QA: {len(findings)} finding(s) block the build" + note
    ]
    lines += [f"  [{f.check}] {f.block}: {f.message}" for f in findings]
    if accepted:
        lines.append("  Accepted by the owner:")
        lines += [
            f"  [{f.check}] {f.block}: {f.message}" + (f" ({why})" if why else "")
            for f, why in accepted
        ]
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
        accepted = stored_accepted(db)
    finally:
        db.close()
    if row is None:
        return
    print(render(found, accepted))
