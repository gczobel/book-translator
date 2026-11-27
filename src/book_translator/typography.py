"""S8a: Spanish typography, applied to the stored targets and checked by QA. No LLM is called.

The normaliser runs after the post-polish fidelity stage and before QA, on every run. It applies
only the mechanical rules of docs/reference/epublibre.md section 3 and section 5.4 that have one
safe reading, and records each change in `typography_changes`. A second run changes nothing
(idempotent). Whatever it cannot fix safely is left as it is and reported by the QA checks
registered below, one per rule family.

Inline codes (`<pc id="n">`, `</pc>`, `<ph id="n"/>`) are lifted out of the text before any rule
runs and put back afterwards, so a rule can never touch them. A rewrite that would break the
block's codes is dropped.
"""

import re
import sqlite3
from collections.abc import Callable

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import InlineCodeError
from book_translator.qa import Finding, QAContext, check

STAGE = "typography"
OPEN_CODE, CLOSE_CODE, STANDALONE_CODE = "", "", ""
_CODE = re.compile(r'<pc id="\d+">|</pc>|<ph id="\d+"/>')
_PLACEHOLDER = re.compile("[-]")


def mask(text: str) -> tuple[str, list[str]]:
    """The text with each inline code replaced by one private character, and the codes."""
    codes: list[str] = []

    def lift(match: re.Match[str]) -> str:
        code = match.group()
        codes.append(code)
        if code == "</pc>":
            return CLOSE_CODE
        return OPEN_CODE if code.startswith("<pc") else STANDALONE_CODE

    return _CODE.sub(lift, text), codes


def unmask(text: str, codes: list[str]) -> str:
    supply = iter(codes)
    return _PLACEHOLDER.sub(lambda _: next(supply), text)


_OPENERS = "  \t\n([{—«“‘" + OPEN_CODE + STANDALONE_CODE
_QUOTE_CHARS = "\"'«»“”‘’"
_LEVELS = (("«", "»"), ("“", "”"), ("‘", "’"))


def _requote(text: str) -> tuple[str, int] | None:
    """The text with its quotes re-set by depth, and the depth left open at its end. None when a
    quote closes what was never opened."""
    out: list[str] = []
    depth = 0
    for index, char in enumerate(text):
        if char not in _QUOTE_CHARS:
            out.append(char)
            continue
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if char in "'’" and before.isalnum() and after.isalnum():
            out.append("’")  # an apostrophe
            continue
        if char in "\"'" and before.isdigit():
            out.append(char)  # Q2: a measure (52° 2' 20")
            continue
        if char == "»" and index == 0:
            out.append(char)  # Q6: a continuation paragraph opens with a closing guillemet
            depth = 1
            continue
        if char in "«“‘" or (char in "\"'" and (not before or before in _OPENERS)):
            depth += 1
            out.append(_LEVELS[min(depth, 3) - 1][0])
            continue
        if depth == 0:
            return None
        tail = ""
        while out and out[-1] in ".,;:":
            tail = out.pop() + tail
        out.append(_LEVELS[min(depth, 3) - 1][1] + tail)
        depth -= 1
    return "".join(out), depth


def quotes(text: str) -> str:
    """Q1-Q4 (3.1): straight and curly quotes are re-set by depth as « » then “ ” then ‘ ’, and a
    period, comma, semicolon or colon inside a closing quote goes outside it. Text whose quotes
    do not pair up is left alone (the `quotes` check reports it)."""
    done = _requote(text)
    return text if done is None or done[1] else done[0]


@check("quotes")
def quote_pairing(context: QAContext) -> list[Finding]:
    """Quotes must pair up. Q6: a quote left open may continue in the next paragraph, which then
    opens with »."""
    pieces = [(b, mask(t)[0]) for b, ts in context.targets.items() for t in ts]
    found = []
    for index, (block, text) in enumerate(pieces):
        done = _requote(text)
        continued = index + 1 < len(pieces) and pieces[index + 1][1].startswith("\u00bb")
        if done is None or (done[1] and not continued):
            found.append(Finding("quotes", block, "its quotes do not pair up"))
        elif done[0] != text:
            found.append(Finding("quotes", block, "its quotes are not set as « » “ ” ‘ ’"))
    return found


RULES: list[tuple[str, Callable[[str], str]]] = [("quotes", quotes)]


def normalise(text: str) -> list[tuple[str, str, str]]:
    """Apply every rule in turn: each change as (rule, old, new), the last new being the result."""
    masked, codes = mask(text)
    changes: list[tuple[str, str, str]] = []
    for name, rule in RULES:
        new = rule(masked)
        if new != masked:
            changes.append((name, unmask(masked, codes), unmask(new, codes)))
            masked = new
    return changes


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "create table if not exists typography_changes (id integer primary key autoincrement,"
        " block text not null, position integer not null, rule text not null,"
        " old text not null, new text not null)"
    )


def apply(db: sqlite3.Connection, source: Epub, bible: Bible) -> None:
    """Normalise every stored target block that has a change to make, and record the changes."""
    rows = db.execute("select source, position, text from targets order by source, position")
    stored = [(str(b), int(p), str(t)) for b, p, t in rows]
    pieces: dict[str, list[str]] = {}
    for block, _, text in stored:
        pieces.setdefault(block, []).append(text)
    with db:
        for block, position, text in stored:
            changes = normalise(text)
            if not changes:
                continue
            result = changes[-1][2]
            fixed = [result if p == position else t for p, t in enumerate(pieces[block])]
            if not _legal(source, block, fixed):
                continue
            db.execute(
                "update targets set text = ? where source = ? and position = ?",
                (result, block, position),
            )
            db.executemany(
                "insert into typography_changes (block, position, rule, old, new)"
                " values (?, ?, ?, ?, ?)",
                [(block, position, rule, old, new) for rule, old, new in changes],
            )
            pieces[block][position] = result


def _legal(source: Epub, block: str, pieces: list[str]) -> bool:
    try:
        source.encode_block(block).validate_pieces(pieces)
    except (InlineCodeError, KeyError):
        return False
    return True
